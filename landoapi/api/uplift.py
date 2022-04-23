# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

from connexion import problem
from flask import current_app, g

from landoapi import auth
from landoapi.repos import get_repos_for_env
from landoapi.uplift import (
    create_uplift_revision,
    check_approval_state,
)
from landoapi.decorators import require_phabricator_api_key

logger = logging.getLogger(__name__)


@require_phabricator_api_key(optional=False)
@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
def create(data):
    """Create new uplift requests for requested repository & revision"""
    repo_name, revision_id = data["repository"], data["revision_id"]

    # Validate repository.
    all_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    repository = all_repos.get(repo_name)
    if repository is None or not repository.approval_required:
        return problem(
            400,
            f"Repository {repo_name} is not a repository known to Lando.",
            "Please select an uplift repository to create the uplift request.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    if not repository.approval_required:
        return problem(
            400,
            f"Repository {repo_name} is not an uplift repository.",
            "",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    logger.info(
        "Checking approval state",
        extra={
            "revision": revision_id,
            "target_repository": repo_name,
        },
    )
    revision, target_repository = check_approval_state(
        g.phabricator,
        revision_id=revision_id,
        target_repository_name=repo_name,
    )
    logger.info(
        "Approval state is valid",
        extra={"style": "uplift"},
    )

    try:
        output = create_uplift_revision(g.phabricator, revision, target_repository)
    except Exception as e:
        logger.error(
            "Failed to create an uplift request",
            extra={
                "revision": revision_id,
                "repository": repository,
                "error": str(e),
            },
        )
        raise

    return output, 201
