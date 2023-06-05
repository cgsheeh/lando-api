# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import functools
import logging

from connexion import ProblemException
from flask import (
    current_app,
    g,
)

from landoapi import auth
from landoapi.models.landing_job import (
    add_job_with_revisions,
    LandingJobStatus,
)
from landoapi.models.revisions import Revision
from landoapi.repos import get_repos_for_env

logger = logging.getLogger(__name__)


def enforce_scm_level_1(func):
    """Decorator to enforce `active_scm_level_1` membership with error messaging."""

    @functools.wraps(func)
    def wrap_api(*args, **kwargs):
        # Return appropriate error message if user does not have commit access.
        if not g.auth0_user.is_in_groups("all_scm_level_1"):
            raise ProblemException(
                401,
                "`scm_level_1` access is required.",
                "You do not have `scm_level_1` commit access.",
                type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
            )

        # Check that user has active_scm_level_1 and not `expired_scm_level_1`.
        if g.auth0_user.is_in_groups(
            "expired_scm_level_1"
        ) or not g.auth0_user.is_in_groups("active_scm_level_1"):
            raise ProblemException(
                401,
                "Your `scm_level_1` commit access has expired.",
                "Your `scm_level_1` commit access has expired.",
                type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
            )

        return func(*args, **kwargs)

    return wrap_api


@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
@enforce_scm_level_1
def post(data: dict):
    # TODO what format should the patch data be?
    # TODO these should probably be base64 encoded.
    base_commit = data["base_commit"]
    patches = data["patches"]

    if not base_commit or len(base_commit) != 40:
        raise ProblemException(
            400,
            "Base commit must be a 40-character commit hash.",
            "Base commit must be a 40-character commit hash.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    if not patches:
        raise ProblemException(
            400,
            "Patches must contain at least 1 patch.",
            "Patches must contain at least 1 patch.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    # TODO better way to get the try repo?
    try_repo = get_repos_for_env(current_app.config.get("ENVIRONMENT")).get("try")
    if not try_repo:
        raise ProblemException(
            500,
            "Could not find a `try` repo to submit to.",
            "Could not find a `try` repo to submit to.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )

    # Add a landing job for this try push.
    ldap_username = g.auth0_user.email
    # TODO do something more useful with `patch_data`.
    revisions = [Revision(patch_bytes=patch, patch_data={}) for patch in patches]
    add_job_with_revisions(
        revisions,
        repository_name=try_repo.short_name,
        repository_url=try_repo.url,
        requester_email=ldap_username,
        status=LandingJobStatus.SUBMITTED,
        target_cset=base_commit,
    )

    return 201, None
