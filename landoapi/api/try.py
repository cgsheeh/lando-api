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
    LandingJob,
    LandingJobStatus,
)
from landoapi.repos import get_repos_for_env
from landoapi.storage import db

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
        if g.auth0_user.is_in_group(
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
    patches = data["patches"]

    # TODO better way to get the try repo?
    try_repo = get_repos_for_env(current_app.config.get("ENVIRONMENT")).get("try")
    if not try_repo:
        raise ProblemException(
            500,
            "Could not find a `try` repo to submit to.",
            "Could not find a `try` repo to submit to.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )

    ldap_username = g.auth0_user.email

    # TODO how to store the data in the DB as a job?
    job = LandingJob(
        requester_email=ldap_username,
        repository_name=try_repo.short_name,
        repository_url=try_repo.url,
        status=LandingJobStatus.SUBMITTED,
    )

    db.session.add(job)
    db.session.commit()

    return 201, None
