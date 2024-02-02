# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Construct an application instance that can be referenced by a WSGI server.
"""
import os

from .app import SUBSYSTEMS, construct_app, construct_treestatus_app, load_config

# Determine which app to construct by looking for a Treestatus specific env variable.
app_constructor = (
    construct_treestatus_app
    if os.getenv("TREESTATUS_APP") is not None
    else construct_app
)

config = load_config()
app = app_constructor(config)
for system in SUBSYSTEMS:
    system.init_app(app.app)

# No need to ready check since that should have already been done by
# lando-cli before execing to uwsgi.
