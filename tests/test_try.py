# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.models.landing_job import LandingJob

PATCH_NORMAL = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".strip()


def test_try_api_requires_data(db, client, auth0_mock, mocked_repo_config):
    try_push_json = {
        "base_commit": "abc",
        "patches": [],
    }
    response = client.post("/try", json=try_push_json, headers=auth0_mock.mock_headers)
    assert (
        response.status_code == 400
    ), "Try push without 40-character base commit should return 400."

    try_push_json["base_commit"] = "abcabcabcaabcabcabcaabcabcabcaabcabcabca"
    response = client.post("/try", json=try_push_json, headers=auth0_mock.mock_headers)
    assert response.status_code == 400, "Try push without patches should return 400."


def test_try_api_success(db, client, auth0_mock, mocked_repo_config):
    try_push_json = {
        "base_commit": "abcabcabcaabcabcabcaabcabcabcaabcabcabca",
        "patches": [PATCH_NORMAL],
    }
    response = client.post("/try", json=try_push_json, headers=auth0_mock.mock_headers)
    assert response.status_code == 201, "Successful try push should return 201."

    queue_items = LandingJob.job_queue_query(
        repositories=["try"], grace_seconds=0
    ).all()
    assert len(queue_items) == 1, "Try push should have created 1 landing job."


# TODO implement
def test_try_landing_job():
    """Test that a Try landing job completes as expected."""
    raise NotImplemented("TODO")


def test_scm_level_1_enforce():
    """Test the scm_level_1 enforcement/error handling.

    TODO should we make the enforcement more generic? Part of the auth0 decorator?
    """
    raise NotImplemented("TODO")
