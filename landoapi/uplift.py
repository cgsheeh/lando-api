# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import logging
import re

from typing import (
    Optional,
    Tuple,
)

from flask import current_app

from landoapi.phabricator import PhabricatorClient
from landoapi.phabricator_patch import patch_to_changes
from landoapi.projects import RELMAN_PROJECT_SLUG
from landoapi.repos import get_repos_for_env
from landoapi.stacks import request_extended_revision_data


logger = logging.getLogger(__name__)


ARC_DIFF_REV_RE = re.compile(
    r"^\s*Differential Revision:\s*(?P<phab_url>https?://.+)/D(?P<rev>\d+)\s*$",
    flags=re.MULTILINE,
)
ORIGINAL_DIFF_REV_RE = re.compile(
    r"^\s*Original Revision:\s*(?P<phab_url>https?://.+)/D(?P<rev>\d+)\s*$",
    flags=re.MULTILINE,
)


def move_drev_to_original(body: str) -> str:
    """Handle moving the `Differential Revision` line.

    Moves the `Differential Revision` line to `Original Revision`, if a link
    to the original revision does not already exist. If the `Original Revision`
    line does exist, scrub the `Differential Revision` line.

    Args:
        body: `str` text of the commit message.

    Returns:
        New commit message body text as `str`,
    """
    differential_revision = ARC_DIFF_REV_RE.search(body)
    original_revision = ORIGINAL_DIFF_REV_RE.search(body)

    # If both match, we already have an `Original Revision` line.
    if differential_revision and original_revision:
        return body

    def repl(match):
        phab_url = match.group("phab_url")
        rev = match.group("rev")
        return f"\nOriginal Revision: {phab_url}/D{rev}"

    # Update the commit message.
    return ARC_DIFF_REV_RE.sub(repl, body)


def get_uplift_request_form(revision) -> Optional[str]:
    """Return the content of the uplift request form or `None` if missing."""
    bug = PhabricatorClient.expect(revision, "fields").get("uplift.request")
    return bug


def get_release_managers(phab: PhabricatorClient) -> dict:
    """Load the release-managers group details from Phabricator"""
    groups = phab.call_conduit(
        "project.search",
        attachments={"members": True},
        constraints={"slugs": [RELMAN_PROJECT_SLUG]},
    )
    return phab.single(groups, "data")


def get_uplift_conduit_state(
    phab: PhabricatorClient, revision_id: int, target_repository_name: str
) -> Tuple[dict, dict]:
    # Load target repo from Phabricator
    target_repo = phab.call_conduit(
        "diffusion.repository.search",
        constraints={"shortNames": [target_repository_name]},
    )
    target_repo = phab.single(target_repo, "data")

    # Load base revision details from Phabricator
    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [revision_id]}
    )
    revision = phab.single(revision, "data")

    return revision, target_repo


def create_uplift_revision(
    phab: PhabricatorClient,
    source_revision: dict,
    target_repository: dict,
) -> dict:
    """Create a new revision on a repository, cloning a diff from another repo.

    Returns a `dict` to be returned as JSON from the uplift API.
    """
    # Check the target repository needs an approval
    repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    local_repo = repos.get(target_repository["fields"]["shortName"])
    assert local_repo is not None, f"Unknown repository {target_repository}"
    assert (
        local_repo.approval_required is True
    ), f"No approval required for {target_repository}"

    # Load release managers group for review
    release_managers = get_release_managers(phab)

    # Find the source diff on phabricator
    stack = request_extended_revision_data(phab, [source_revision["phid"]])
    diff = stack.diffs[source_revision["fields"]["diffPHID"]]

    # Get raw diff
    raw_diff = phab.call_conduit("differential.getrawdiff", diffID=diff["id"])
    if not raw_diff:
        raise Exception("Missing raw source diff, cannot uplift revision.")

    # Base revision hash is available on the diff fields
    refs = {ref["type"]: ref for ref in phab.expect(diff, "fields", "refs")}
    base_revision = refs["base"]["identifier"] if "base" in refs else None

    # The first commit in the attachment list is the current HEAD of stack
    # we can use the HEAD to mark the changes being created
    commits = phab.expect(diff, "attachments", "commits", "commits")
    head = commits[0] if commits else None

    # Upload it on target repo
    new_diff = phab.call_conduit(
        "differential.creatediff",
        changes=patch_to_changes(raw_diff, head["identifier"] if head else None),
        sourceMachine=local_repo.url,
        sourceControlSystem="hg",
        sourceControlPath="/",
        sourceControlBaseRevision=base_revision,
        creationMethod="lando-uplift",
        lintStatus="none",
        unitStatus="none",
        repositoryPHID=target_repository["phid"],
        sourcePath=None,  # TODO ? Local path
        branch="HEAD",
    )
    new_diff_id = phab.expect(new_diff, "diffid")
    new_diff_phid = phab.expect(new_diff, "phid")
    logger.info("Created new diff", extra={"id": new_diff_id, "phid": new_diff_phid})

    # Attach commit information to setup the author (needed for landing)
    phab.call_conduit(
        "differential.setdiffproperty",
        diff_id=new_diff_id,
        name="local:commits",
        data=json.dumps(
            {
                commit["identifier"]: {
                    "author": phab.expect(commit, "author", "name"),
                    "authorEmail": phab.expect(commit, "author", "email"),
                    "time": 0,
                    "message": phab.expect(commit, "message"),
                    "rev": phab.expect(commit, "identifier"),
                    "tree": None,
                    "parents": phab.expect(commit, "parents"),
                }
                for commit in commits
            }
        ),
    )

    # Update `Differential Revision` to `Original Revision`.
    summary = str(phab.expect(source_revision, "fields", "summary"))
    summary = move_drev_to_original(summary)

    # Finally create the revision to link all the pieces
    new_rev = phab.call_conduit(
        "differential.revision.edit",
        transactions=[
            {"type": "update", "value": new_diff_phid},
            # Copy title & summary from source revision
            {"type": "title", "value": phab.expect(source_revision, "fields", "title")},
            {"type": "summary", "value": summary},
            # Set release managers as reviewers
            {
                "type": "reviewers.add",
                "value": [f"blocking({release_managers['phid']})"],
            },
            # Copy Bugzilla id
            {
                "type": "bugzilla.bug-id",
                "value": phab.expect(source_revision, "fields", "bugzilla.bug-id"),
            },
        ],
    )
    new_rev_id = phab.expect(new_rev, "object", "id")
    new_rev_phid = phab.expect(new_rev, "object", "phid")
    logger.info(
        "Created new Phabricator revision",
        extra={"id": new_rev_id, "phid": new_rev_phid},
    )

    return {
        "mode": "uplift",
        "repository": phab.expect(target_repository, "fields", "shortName"),
        "url": f"{phab.url_base}/D{new_rev_id}",
        "revision_id": new_rev_id,
        "revision_phid": new_rev_phid,
        "diff_id": new_diff_id,
        "diff_phid": new_diff_phid,
    }


def stack_uplift_form_submitted(stack_data) -> bool:
    """Return `True` if the stack has a valid uplift request form submitted."""
    # NOTE: this just checks that any of the revisions in the stack have the uplift form
    # submitted.
    return any(
        get_uplift_request_form(revision) for revision in stack_data.revisions.values()
    )
