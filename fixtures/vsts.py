from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import responses

from sentry.integrations.vsts import VstsIntegrationProvider
from sentry.testutils.cases import IntegrationTestCase


class VstsIntegrationTestCase(IntegrationTestCase):
    provider = VstsIntegrationProvider()

    def setUp(self):
        super().setUp()

        self.access_token = "9d646e20-7a62-4bcc-abc0-cb2d4d075e36"
        self.refresh_token = "32004633-a3c0-4616-9aa0-a40632adac77"

        self.vsts_account_id = "c8a585ae-b61f-4ba6-833c-9e8d5d1674d8"
        self.vsts_account_name = "MyVSTSAccount"
        self.vsts_account_uri = "https://MyVSTSAccount.vssps.visualstudio.com:443/"
        self.vsts_base_url = "https://MyVSTSAccount.visualstudio.com/"

        self.vsts_user_id = "d6245f20-2af8-44f4-9451-8107cb2767db"
        self.vsts_user_name = "Foo Bar"
        self.vsts_user_email = "foobar@example.com"

        self.repo_id = "47166099-3e16-4868-9137-22ac6b05b06e"
        self.repo_name = "cool-service"

        self.project_a = {"id": "eb6e4656-77fc-42a1-9181-4c6d8e9da5d1", "name": "ProjectA"}

        self.project_b = {"id": "6ce954b1-ce1f-45d1-b94d-e6bf2464ba2c", "name": "ProjectB"}

        responses.start()
        self._stub_vsts()

    def tearDown(self):
        responses.stop()

    def _stub_vsts(self):
        responses.reset()

        responses.add(
            responses.POST,
            "https://app.vssps.visualstudio.com/oauth2/token",
            json={
                "access_token": self.access_token,
                "token_type": "grant",
                "expires_in": 300,  # seconds (5 min)
                "refresh_token": self.refresh_token,
            },
        )

        responses.add(
            responses.GET,
            "https://app.vssps.visualstudio.com/_apis/accounts?memberId=%s&api-version=4.1"
            % self.vsts_user_id,
            json={
                "count": 1,
                "value": [
                    {
                        "accountId": self.vsts_account_id,
                        "accountUri": self.vsts_account_uri,
                        "accountName": self.vsts_account_name,
                        "properties": {},
                    }
                ],
            },
        )

        responses.add(
            responses.GET,
            "https://app.vssps.visualstudio.com/_apis/resourceareas/79134C72-4A58-4B42-976C-04E7115F32BF?hostId=%s&api-preview=5.0-preview.1"
            % self.vsts_account_id,
            json={"locationUrl": self.vsts_base_url},
        )
        responses.add(
            responses.GET,
            "https://app.vssps.visualstudio.com/_apis/profile/profiles/me?api-version=1.0",
            json={
                "id": self.vsts_user_id,
                "displayName": self.vsts_user_name,
                "emailAddress": self.vsts_user_email,
            },
        )

        responses.add(
            responses.GET,
            "https://app.vssps.visualstudio.com/_apis/connectionData/",
            json={"authenticatedUser": {"subjectDescriptor": self.vsts_account_id}},
        )

        responses.add(
            responses.GET,
            f"https://{self.vsts_account_name.lower()}.visualstudio.com/_apis/projects",
            json={"value": [self.project_a, self.project_b], "count": 2},
        )

        responses.add(
            responses.POST,
            f"https://{self.vsts_account_name.lower()}.visualstudio.com/_apis/hooks/subscriptions",
            json=CREATE_SUBSCRIPTION,
        )

        responses.add(
            responses.GET,
            f"https://{self.vsts_account_name.lower()}.visualstudio.com/_apis/git/repositories",
            json={
                "value": [
                    {
                        "id": self.repo_id,
                        "name": self.repo_name,
                        "project": {"name": self.project_a["name"]},
                    }
                ]
            },
        )

        responses.add(
            responses.GET,
            f"https://{self.vsts_account_name.lower()}.visualstudio.com/ProjectA/_apis/git/repositories/ProjectA",
            json={
                "repository": {
                    "id": self.repo_id,
                    "name": self.repo_name,
                    "project": {"name": self.project_a["name"]},
                }
            },
        )

        for project in [self.project_a, self.project_b]:
            responses.add(
                responses.GET,
                "https://{}.visualstudio.com/{}/_apis/wit/workitemtypes/{}/states".format(
                    self.vsts_account_name.lower(), project["id"], "Bug"
                ),
                json={
                    "count": 6,
                    "value": [
                        {"name": "resolve_status"},
                        {"name": "resolve_when"},
                        {"name": "regression_status"},
                        {"name": "sync_comments"},
                        {"name": "sync_forward_assignment"},
                        {"name": "sync_reverse_assignment"},
                    ],
                },
            )
            responses.add(
                responses.GET,
                "https://{}.visualstudio.com/{}/_apis/wit/workitemtypes/{}/states".format(
                    self.vsts_account_name.lower(), project["id"], "Issue"
                ),
                json={
                    "count": 0,
                    "value": [],
                },
            )
            responses.add(
                responses.GET,
                "https://{}.visualstudio.com/{}/_apis/wit/workitemtypes/{}/states".format(
                    self.vsts_account_name.lower(), project["id"], "Task"
                ),
                json={
                    "count": 0,
                    "value": [],
                },
            )

    def make_init_request(self, path=None, body=None):
        return self.client.get(path or self.init_path, body or {})

    def make_oauth_redirect_request(self, state):
        return self.client.get(
            "{}?{}".format(self.setup_path, urlencode({"code": "oauth-code", "state": state}))
        )

    def assert_vsts_oauth_redirect(self, redirect):
        assert redirect.scheme == "https"
        assert redirect.netloc == "app.vssps.visualstudio.com"
        assert redirect.path == "/oauth2/authorize"

    def assert_account_selection(self, response, account_id=None):
        account_id = account_id or self.vsts_account_id
        assert response.status_code == 200
        assert f'<option value="{account_id}"'.encode() in response.content

    def assert_installation(self):
        # Initial request to the installation URL for VSTS
        resp = self.make_init_request()
        redirect = urlparse(resp["Location"])

        assert resp.status_code == 302
        self.assert_vsts_oauth_redirect(redirect)

        query = parse_qs(redirect.query)

        # OAuth redirect back to Sentry (identity_pipeline_view)
        resp = self.make_oauth_redirect_request(query["state"][0])
        self.assert_account_selection(resp)

        # User choosing which VSTS Account to use (AccountConfigView)
        # Final step.
        resp = self.client.post(
            self.setup_path, {"account": self.vsts_account_id, "provider": "vsts"}
        )
        return resp


COMPARE_COMMITS_EXAMPLE = b"""
{
  "count": 1,
  "value": [
    {
      "commitId": "6c36052c58bde5e57040ebe6bdb9f6a52c906fff",
      "author": {
        "name": "max bittker",
        "email": "max@sentry.io",
        "date": "2018-04-24T00:03:18Z"
      },
      "committer": {
        "name": "max bittker",
        "email": "max@sentry.io",
        "date": "2018-04-24T00:03:18Z"
      },
      "comment": "Updated README.md",
      "commentTruncated": true,
      "changeCounts": {"Add": 0, "Edit": 1, "Delete": 0},
      "url":
        "https://mbittker.visualstudio.com/_apis/git/repositories/b1e25999-c080-4ea1-8c61-597c4ec41f06/commits/6c36052c58bde5e57040ebe6bdb9f6a52c906fff",
      "remoteUrl":
        "https://mbittker.visualstudio.com/_git/MyFirstProject/commit/6c36052c58bde5e57040ebe6bdb9f6a52c906fff"
    }
  ]
}
"""

COMMIT_DETAILS_EXAMPLE = r"""
{
    "_links": {
        "changes": {
            "href": "https://mbittker.visualstudio.com/_apis/git/repositories/666ffcce-8ffa-46ec-bccf-b93b55bb2320/commits/6c36052c58bde5e57040ebe6bdb9f6a52c906fff/changes"
        },
        "repository": {
            "href": "https://mbittker.visualstudio.com/_apis/git/repositories/666ffcce-8ffa-46ec-bccf-b93b55bb2320"
        },
        "self": {
            "href": "https://mbittker.visualstudio.com/_apis/git/repositories/666ffcce-8ffa-46ec-bccf-b93b55bb2320/commits/6c36052c58bde5e57040ebe6bdb9f6a52c906fff"
        },
        "web": {
            "href": "https://mbittker.visualstudio.com/_git/MyFirstProject/commit/6c36052c58bde5e57040ebe6bdb9f6a52c906fff"
        }
    },
    "author": {
        "date": "2018-11-23T15:59:19Z",
        "email": "max@sentry.io",
        "imageUrl": "https://www.gravatar.com/avatar/1cee8d752bcad4c172d60e56bb398c11?r=g&d=mm",
        "name": "max bitker"
    },
    "comment": "Updated README.md\n\nSecond line\n\nFixes SENTRY-1",
    "commitId": "6c36052c58bde5e57040ebe6bdb9f6a52c906fff",
    "committer": {
        "date": "2018-11-23T15:59:19Z",
        "email": "max@sentry.io",
        "imageUrl": "https://www.gravatar.com/avatar/1cee8d752bcad4c172d60e56bb398c11?r=g&d=mm",
        "name": "max bittker"
    },
    "parents": [
        "641e82ce0ed14f3cf3670b0bf5f669d7fbd40a68"
    ],
    "push": {
        "date": "2018-11-23T16:01:10.7246278Z",
        "pushId": 2,
        "pushedBy": {
            "_links": {
                "avatar": {
                    "href": "https://mbittker.visualstudio.com/_apis/GraphProfile/MemberAvatars/msa.NjI0ZGRhOWMtODgyZC03ZmRhLTk3OWItZTdhMjI5MWMzMzBk"
                }
            },
            "descriptor": "msa.NjI0ZGRhOWMtODgyZC03ZmRhLTk3OWItZTdhMjI5MWMzMzBk",
            "displayName": "Mark Story",
            "id": "624dda9c-882d-6fda-979b-e7a2291c330d",
            "imageUrl": "https://mbittker.visualstudio.com/_api/_common/identityImage?id=624dda9c-882d-6fda-979b-e7a2291c330d",
            "uniqueName": "mark@mark-story.com",
            "url": "https://mbittker.visualstudio.com/Aa365971d-9897-47eb-becf-c5142d33db08/_apis/Identities/624dda9c-882d-6fda-979b-e7a2291c330d"
        }
    },
    "remoteUrl": "https://mbittker.visualstudio.com/MyFirstProject/_git/box-of-things/commit/6c36052c58bde5e57040ebe6bdb9f6a52c906fff",
    "treeId": "026257a5e53eb923497c0217ef76e567f3a60088",
    "url": "https://mbittker.visualstudio.com/_apis/git/repositories/666ffcce-8ffa-46ec-bccf-b93b55bb2320/commits/6c36052c58bde5e57040ebe6bdb9f6a52c906fff"
}
"""


FILE_CHANGES_EXAMPLE = b"""
{
  "changeCounts": {"Edit": 1},
  "changes": [
    {
      "item": {
        "objectId": "b48e843656a0a12926a0bcedefe8ef3710fe2867",
        "originalObjectId": "270b590a4edf3f19aa7acc7b57379729e34fc681",
        "gitObjectType": "blob",
        "commitId": "6c36052c58bde5e57040ebe6bdb9f6a52c906fff",
        "path": "/README.md",
        "url":
          "https://mbittker.visualstudio.com/DefaultCollection/_apis/git/repositories/b1e25999-c080-4ea1-8c61-597c4ec41f06/items/README.md?versionType=Commit&version=6c36052c58bde5e57040ebe6bdb9f6a52c906fff"
      },
      "changeType": "edit"
    }
  ]
}
"""

WORK_ITEM_RESPONSE = """{
  "id": 309,
  "rev": 1,
  "fields": {
    "System.AreaPath": "Fabrikam-Fiber-Git",
    "System.TeamProject": "Fabrikam-Fiber-Git",
    "System.IterationPath": "Fabrikam-Fiber-Git",
    "System.WorkItemType": "Product Backlog Item",
    "System.State": "New",
    "System.Reason": "New backlog item",
    "System.CreatedDate": "2015-01-07T18:13:01.807Z",
    "System.CreatedBy": "Jamal Hartnett <fabrikamfiber4@hotmail.com>",
    "System.ChangedDate": "2015-01-07T18:13:01.807Z",
    "System.ChangedBy": "Jamal Hartnett <fabrikamfiber4@hotmail.com>",
    "System.Title": "Hello",
    "Microsoft.VSTS.Scheduling.Effort": 8,
    "WEF_6CB513B6E70E43499D9FC94E5BBFB784_Kanban.Column": "New",
    "System.Description": "Fix this."
  },
  "_links": {
    "self": {
      "href": "https://fabrikam-fiber-inc.visualstudio.com/DefaultCollection/_apis/wit/workItems/309"
    },
    "workItemUpdates": {
      "href": "https://fabrikam-fiber-inc.visualstudio.com/DefaultCollection/_apis/wit/workItems/309/updates"
    },
    "workItemRevisions": {
      "href": "https://fabrikam-fiber-inc.visualstudio.com/DefaultCollection/_apis/wit/workItems/309/revisions"
    },
    "workItemHistory": {
      "href": "https://fabrikam-fiber-inc.visualstudio.com/DefaultCollection/_apis/wit/workItems/309/history"
    },
    "html": {
      "href": "https://fabrikam-fiber-inc.visualstudio.com/web/wi.aspx?pcguid=d81542e4-cdfa-4333-b082-1ae2d6c3ad16&id=309"
    },
    "workItemType": {
      "href": "https://fabrikam-fiber-inc.visualstudio.com/DefaultCollection/6ce954b1-ce1f-45d1-b94d-e6bf2464ba2c/_apis/wit/workItemTypes/Product%20Backlog%20Item"
    },
    "fields": {
      "href": "https://fabrikam-fiber-inc.visualstudio.com/DefaultCollection/_apis/wit/fields"
    }
  },
  "url": "https://fabrikam-fiber-inc.visualstudio.com/DefaultCollection/_apis/wit/workItems/309"
}"""

GET_USERS_RESPONSE = b"""{
  "count": 4,
  "value": [
    {
      "subjectKind": "user",
      "cuid": "ec09a4d8-d914-4f28-9e39-23d52b683f90",
      "domain": "Build",
      "principalName": "51ac8d19-6694-459f-a65e-bec30e9e2e33",
      "mailAddress": "",
      "origin": "vsts",
      "originId": "ec09a4d8-d914-4f28-9e39-23d52b683f90",
      "displayName": "Project Collection Build Service (Ftottentest2)",
      "_links": {
        "self": {
          "href": "https://fabrikam.vssps.visualstudio.com/_apis/graph/users/TWljcm9zb2Z0LlRlYW1Gb3VuZGF0aW9uLlNlcnZpY2VJZGVudGl0eTtmMzViOTAxNS1jZGU4LTQ4MzQtYTFkNS0wOWU4ZjM1OWNiODU6QnVpbGQ6NTFhYzhkMTktNjY5NC00NTlmLWE2NWUtYmVjMzBlOWUyZTMz"
        },
        "memberships": {
          "href": "https://fabrikam.vssps.visualstudio.com/_apis/graph/memberships/TWljcm9zb2Z0LlRlYW1Gb3VuZGF0aW9uLlNlcnZpY2VJZGVudGl0eTtmMzViOTAxNS1jZGU4LTQ4MzQtYTFkNS0wOWU4ZjM1OWNiODU6QnVpbGQ6NTFhYzhkMTktNjY5NC00NTlmLWE2NWUtYmVjMzBlOWUyZTMz"
        }
      },
      "url": "https://fabrikam.vssps.visualstudio.com/_apis/graph/users/TWljcm9zb2Z0LlRlYW1Gb3VuZGF0aW9uLlNlcnZpY2VJZGVudGl0eTtmMzViOTAxNS1jZGU4LTQ4MzQtYTFkNS0wOWU4ZjM1OWNiODU6QnVpbGQ6NTFhYzhkMTktNjY5NC00NTlmLWE2NWUtYmVjMzBlOWUyZTMz",
      "descriptor": "TWljcm9zb2Z0LlRlYW1Gb3VuZGF0aW9uLlNlcnZpY2VJZGVudGl0eTtmMzViOTAxNS1jZGU4LTQ4MzQtYTFkNS0wOWU4ZjM1OWNiODU6QnVpbGQ6NTFhYzhkMTktNjY5NC00NTlmLWE2NWUtYmVjMzBlOWUyZTMz"
    },
    {
      "subjectKind": "user",
      "metaType": "member",
      "cuid": "00ca946b-2fe9-4f2a-ae2f-40d5c48001bc",
      "domain": "LOCAL AUTHORITY",
      "principalName": "TeamFoundationService (TEAM FOUNDATION)",
      "mailAddress": "",
      "origin": "vsts",
      "originId": "00ca946b-2fe9-4f2a-ae2f-40d5c48001bc",
      "displayName": "TeamFoundationService (TEAM FOUNDATION)",
      "_links": {
        "self": {
          "href": "https://fabrikam.vssps.visualstudio.com/_apis/graph/users/TWljcm9zb2Z0LklkZW50aXR5TW9kZWwuQ2xhaW1zLkNsYWltc0lkZW50aXR5Ozc3ODlmMDlkLWUwNTMtNGYyZS1iZGVlLTBjOGY4NDc2YTRiYw"
        },
        "memberships": {
          "href": "https://fabrikam.vssps.visualstudio.com/_apis/graph/memberships/TWljcm9zb2Z0LklkZW50aXR5TW9kZWwuQ2xhaW1zLkNsYWltc0lkZW50aXR5Ozc3ODlmMDlkLWUwNTMtNGYyZS1iZGVlLTBjOGY4NDc2YTRiYw"
        }
      },
      "url": "https://fabrikam.vssps.visualstudio.com/_apis/graph/users/TWljcm9zb2Z0LklkZW50aXR5TW9kZWwuQ2xhaW1zLkNsYWltc0lkZW50aXR5Ozc3ODlmMDlkLWUwNTMtNGYyZS1iZGVlLTBjOGY4NDc2YTRiYw",
      "descriptor": "TWljcm9zb2Z0LklkZW50aXR5TW9kZWwuQ2xhaW1zLkNsYWltc0lkZW50aXR5Ozc3ODlmMDlkLWUwNTMtNGYyZS1iZGVlLTBjOGY4NDc2YTRiYw"
    },
    {
      "subjectKind": "user",
      "metaType": "member",
      "cuid": "ddd94918-1fc8-459b-994a-cca86c4fbe95",
      "domain": "TEAM FOUNDATION",
      "principalName": "Anonymous",
      "mailAddress": "",
      "origin": "vsts",
      "originId": "ddd94918-1fc8-459b-994a-cca86c4fbe95",
      "displayName": "Anonymous",
      "_links": {
        "self": {
          "href": "https://fabrikam.vssps.visualstudio.com/_apis/graph/users/TWljcm9zb2Z0LlRlYW1Gb3VuZGF0aW9uLlVuYXV0aGVudGljYXRlZElkZW50aXR5O1MtMS0wLTA"
        },
        "memberships": {
          "href": "https://fabrikam.vssps.visualstudio.com/_apis/graph/memberships/TWljcm9zb2Z0LlRlYW1Gb3VuZGF0aW9uLlVuYXV0aGVudGljYXRlZElkZW50aXR5O1MtMS0wLTA"
        }
      },
      "url": "https://fabrikam.vssps.visualstudio.com/_apis/graph/users/TWljcm9zb2Z0LlRlYW1Gb3VuZGF0aW9uLlVuYXV0aGVudGljYXRlZElkZW50aXR5O1MtMS0wLTA",
      "descriptor": "TWljcm9zb2Z0LlRlYW1Gb3VuZGF0aW9uLlVuYXV0aGVudGljYXRlZElkZW50aXR5O1MtMS0wLTA"
    },
    {
      "subjectKind": "user",
      "metaType": "member",
      "cuid": "65903f92-53dc-61b3-bb0e-e69cfa1cb719",
      "domain": "45aa3d2d-7442-473d-b4d3-3c670da9dd96",
      "principalName": "ftotten@vscsi.us",
      "mailAddress": "ftotten@vscsi.us",
      "origin": "aad",
      "originId": "4be8f294-000d-4431-8506-57420b88e204",
      "displayName": "Francis Totten",
      "_links": {
        "self": {
          "href": "https://fabrikam.vssps.visualstudio.com/_apis/graph/users/TWljcm9zb2Z0LklkZW50aXR5TW9kZWwuQ2xhaW1zLkNsYWltc0lkZW50aXR5OzQ1YWEzZDJkLTc0NDItNDczZC1iNGQzLTNjNjcwZGE5ZGQ5NlxmdG90dGVuQHZzY3NpLnVz"
        },
        "memberships": {
          "href": "https://fabrikam.vssps.visualstudio.com/_apis/graph/memberships/TWljcm9zb2Z0LklkZW50aXR5TW9kZWwuQ2xhaW1zLkNsYWltc0lkZW50aXR5OzQ1YWEzZDJkLTc0NDItNDczZC1iNGQzLTNjNjcwZGE5ZGQ5NlxmdG90dGVuQHZzY3NpLnVz"
        }
      },
      "url": "https://fabrikam.vssps.visualstudio.com/_apis/graph/users/TWljcm9zb2Z0LklkZW50aXR5TW9kZWwuQ2xhaW1zLkNsYWltc0lkZW50aXR5OzQ1YWEzZDJkLTc0NDItNDczZC1iNGQzLTNjNjcwZGE5ZGQ5NlxmdG90dGVuQHZzY3NpLnVz",
      "descriptor": "TWljcm9zb2Z0LklkZW50aXR5TW9kZWwuQ2xhaW1zLkNsYWltc0lkZW50aXR5OzQ1YWEzZDJkLTc0NDItNDczZC1iNGQzLTNjNjcwZGE5ZGQ5NlxmdG90dGVuQHZzY3NpLnVz"
    }
  ]
}
"""

CREATE_SUBSCRIPTION = {
    "id": "fd672255-8b6b-4769-9260-beea83d752ce",
    "url": "https://fabrikam.visualstudio.com/_apis/hooks/subscriptions/fd672255-8b6b-4769-9260-beea83d752ce",
    "publisherId": "tfs",
    "eventType": "workitem.update",
    "resourceVersion": "1.0-preview.1",
    "eventDescription": "WorkItem Updated",
    "consumerId": "webHooks",
    "consumerActionId": "httpRequest",
    "actionDescription": "To host myservice",
    "createdBy": {"id": "00ca946b-2fe9-4f2a-ae2f-40d5c48001bc"},
    "createdDate": "2014-10-27T15:37:24.873Z",
    "modifiedBy": {"id": "00ca946b-2fe9-4f2a-ae2f-40d5c48001bc"},
    "modifiedDate": "2014-10-27T15:37:26.23Z",
    "publisherInputs": {
        "buildStatus": "Failed",
        "definitionName": "MyWebSite CI",
        "hostId": "d81542e4-cdfa-4333-b082-1ae2d6c3ad16",
        "projectId": "6ce954b1-ce1f-45d1-b94d-e6bf2464ba2c",
        "tfsSubscriptionId": "3e8b33e7-426d-4c92-9bf9-58e163dd7dd5",
    },
    "consumerInputs": {"url": "https://myservice/newreceiver"},
}

WORK_ITEM_UPDATED: dict[str, Any] = {
    "resourceContainers": {
        "project": {
            "id": "c0bf429a-c03c-4a99-9336-d45be74db5a6",
            "baseUrl": "https://laurynsentry.visualstudio.com/",
        },
        "account": {
            "id": "90e9a854-eb98-4c56-ae1a-035a0f331dd6",
            "baseUrl": "https://laurynsentry.visualstudio.com/",
        },
        "collection": {
            "id": "80ded3e8-3cd3-43b1-9f96-52032624aa3a",
            "baseUrl": "https://laurynsentry.visualstudio.com/",
        },
    },
    "resource": {
        "revisedBy": {
            "displayName": "lauryn",
            "name": "lauryn <lauryn@sentry.io>",
            "url": "https://app.vssps.visualstudio.com/A90e9a854-eb98-4c56-ae1a-035a0f331dd6/_apis/Identities/21354f98-ab06-67d9-b974-5a54d992082e",
            "imageUrl": "https://laurynsentry.visualstudio.com/_api/_common/identityImage?id=21354f98-ab06-67d9-b974-5a54d992082e",
            "descriptor": "msa.MjEzNTRmOTgtYWIwNi03N2Q5LWI5NzQtNWE1NGQ5OTIwODJl",
            "_links": {
                "avatar": {
                    "href": "https://laurynsentry.visualstudio.com/_apis/GraphProfile/MemberAvatars/msa.MjEzNTRmOTgtYWIwNi03N2Q5LWI5NzQtNWE1NGQ5OTIwODJl"
                }
            },
            "uniqueName": "lauryn@sentry.io",
            "id": "21354f98-ab06-67d9-b974-5a54d992082e",
        },
        "revisedDate": "9999-01-01T00:00:00Z",
        "url": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/31/updates/2",
        "fields": {
            "System.AuthorizedDate": {
                "newValue": "2018-07-05T20:52:14.777Z",
                "oldValue": "2018-07-05T20:51:58.927Z",
            },
            "System.AssignedTo": {
                "newValue": "lauryn <lauryn@sentry.io>",
                "oldValue": "lauryn2 <lauryn2@sentry.io>",
            },
            "System.Watermark": {"newValue": 78, "oldValue": 77},
            "System.Rev": {"newValue": 2, "oldValue": 1},
            "System.RevisedDate": {
                "newValue": "9999-01-01T00:00:00Z",
                "oldValue": "2018-07-05T20:52:14.777Z",
            },
            "System.ChangedDate": {
                "newValue": "2018-07-05T20:52:14.777Z",
                "oldValue": "2018-07-05T20:51:58.927Z",
            },
        },
        "workItemId": 31,
        "rev": 2,
        "_links": {
            "self": {
                "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/31/updates/2"
            },
            "workItemUpdates": {
                "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/31/updates"
            },
            "html": {
                "href": "https://laurynsentry.visualstudio.com/web/wi.aspx?pcguid=80ded3e8-3cd3-43b1-9f96-52032624aa3a&id=31"
            },
            "parent": {
                "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/31"
            },
        },
        "id": 2,
        "revision": {
            "url": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/31/revisions/2",
            "fields": {
                "System.AreaPath": "MyFirstProject",
                "System.WorkItemType": "Bug",
                "System.Reason": "New",
                "System.Title": "NameError: global name 'BitbucketRepositoryProvider' is not defined",
                "Microsoft.VSTS.Common.Priority": 2,
                "System.CreatedBy": "lauryn <lauryn@sentry.io>",
                "System.AssignedTo": "lauryn <lauryn@sentry.io>",
                "System.CreatedDate": "2018-07-05T20:51:58.927Z",
                "System.TeamProject": "MyFirstProject",
                "Microsoft.VSTS.Common.Severity": "3 - Medium",
                "Microsoft.VSTS.Common.ValueArea": "Business",
                "System.State": "New",
                "System.Description": "<p><a href=\"https://lauryn.ngrok.io/sentry/internal/issues/55/\">https://lauryn.ngrok.io/sentry/internal/issues/55/</a></p>\n<pre><code>NameError: global name 'BitbucketRepositoryProvider' is not defined\n(1 additional frame(s) were not displayed)\n...\n  File &quot;sentry/runner/__init__.py&quot;, line 125, in configure\n    configure(ctx, py, yaml, skip_service_validation)\n  File &quot;sentry/runner/settings.py&quot;, line 152, in configure\n    skip_service_validation=skip_service_validation\n  File &quot;sentry/runner/initializer.py&quot;, line 315, in initialize_app\n    register_plugins(settings)\n  File &quot;sentry/runner/initializer.py&quot;, line 60, in register_plugins\n    integration.setup()\n  File &quot;sentry/integrations/bitbucket/integration.py&quot;, line 78, in setup\n    BitbucketRepositoryProvider,\n\nNameError: global name 'BitbucketRepositoryProvider' is not defined\n</code></pre>\n",
                "System.ChangedBy": "lauryn <lauryn@sentry.io>",
                "System.ChangedDate": "2018-07-05T20:52:14.777Z",
                "Microsoft.VSTS.Common.StateChangeDate": "2018-07-05T20:51:58.927Z",
                "System.IterationPath": "MyFirstProject",
            },
            "rev": 2,
            "id": 31,
            "_links": {
                "self": {
                    "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/31/revisions/2"
                },
                "workItemRevisions": {
                    "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/31/revisions"
                },
                "parent": {
                    "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/31"
                },
            },
        },
    },
    "eventType": "workitem.updated",
    "detailedMessage": None,
    "createdDate": "2018-07-05T20:52:16.3051288Z",
    "id": "18f51331-2640-4bce-9ebd-c59c855956a2",
    "resourceVersion": "1.0",
    "notificationId": 1,
    "subscriptionId": "7bf628eb-b3a7-4fb2-ab4d-8b60f2e8cb9b",
    "publisherId": "tfs",
    "message": None,
}


WORK_ITEM_UNASSIGNED: dict[str, Any] = {
    "resourceContainers": {
        "project": {
            "id": "c0bf429a-c03c-4a99-9336-d45be74db5a6",
            "baseUrl": "https://laurynsentry.visualstudio.com/",
        },
        "account": {
            "id": "90e9a854-eb98-4c56-ae1a-035a0f331dd6",
            "baseUrl": "https://laurynsentry.visualstudio.com/",
        },
        "collection": {
            "id": "80ded3e8-3cd3-43b1-9f96-52032624aa3a",
            "baseUrl": "https://laurynsentry.visualstudio.com/",
        },
    },
    "resource": {
        "revisedBy": {
            "displayName": "lauryn",
            "name": "lauryn <lauryn@sentry.io>",
            "url": "https://app.vssps.visualstudio.com/A90e9a854-eb98-4c56-ae1a-035a0f331dd6/_apis/Identities/21354f98-ab06-67d9-b974-5a54d992082e",
            "imageUrl": "https://laurynsentry.visualstudio.com/_api/_common/identityImage?id=21354f98-ab06-67d9-b974-5a54d992082e",
            "descriptor": "msa.MjEzNTRmOTgtYWIwNi03N2Q5LWI5NzQtNWE1NGQ5OTIwODJl",
            "_links": {
                "avatar": {
                    "href": "https://laurynsentry.visualstudio.com/_apis/GraphProfile/MemberAvatars/msa.MjEzNTRmOTgtYWIwNi03N2Q5LWI5NzQtNWE1NGQ5OTIwODJl"
                }
            },
            "uniqueName": "lauryn@sentry.io",
            "id": "21354f98-ab06-67d9-b974-5a54d992082e",
        },
        "revisedDate": "9999-01-01T00:00:00      Z",
        "url": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/updates/3",
        "fields": {
            "System.AuthorizedDate": {
                "newValue": "2018-07-05T23:23:09.493            Z",
                "oldValue": "2018-07-05T23:21:38.243            Z",
            },
            "System.AssignedTo": {"oldValue": "lauryn <lauryn@sentry.io>"},
            "System.Watermark": {"newValue": 83, "oldValue": 82},
            "System.Rev": {"newValue": 3, "oldValue": 2},
            "System.RevisedDate": {
                "newValue": "9999-01-01T00:00:00            Z",
                "oldValue": "2018-07-05T23:23:09.493            Z",
            },
            "System.ChangedDate": {
                "newValue": "2018-07-05T23:23:09.493            Z",
                "oldValue": "2018-07-05T23:21:38.243            Z",
            },
        },
        "workItemId": 33,
        "rev": 3,
        "_links": {
            "self": {
                "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/updates/3"
            },
            "workItemUpdates": {
                "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/updates"
            },
            "html": {
                "href": "https://laurynsentry.visualstudio.com/web/wi.aspx?pcguid=80ded3e8-3cd3-43b1-9f96-52032624aa3a&id=33"
            },
            "parent": {
                "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33"
            },
        },
        "id": 3,
        "revision": {
            "url": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/revisions/3",
            "fields": {
                "System.AreaPath": "MyFirstProject",
                "System.WorkItemType": "Bug",
                "System.Reason": "New",
                "System.Title": "NotImplementedError:Visual Studio Team Services requires an organization_id",
                "Microsoft.VSTS.Common.Priority": 2,
                "System.CreatedBy": "lauryn <lauryn@sentry.io>",
                "Microsoft.VSTS.Common.StateChangeDate": "2018-07-05T23:21:25.847            Z",
                "System.CreatedDate": "2018-07-05T23:21:25.847            Z",
                "System.TeamProject": "MyFirstProject",
                "Microsoft.VSTS.Common.ValueArea": "Business",
                "System.State": "New",
                "System.Description": '<p><a href="https:            //lauryn.ngrok.io/sentry/internal/issues/196/">https:            //lauryn.ngrok.io/sentry/internal/issues/196/</a></p>\n<pre><code>NotImplementedError:Visual Studio Team Services requires an organization_id\n(57 additional frame(s) were not displayed)\n...\n  File &quot;sentry/tasks/base.py&quot;',
                "System.ChangedBy": "lauryn <lauryn@sentry.io>",
                "System.ChangedDate": "2018-07-05T23:23:09.493            Z",
                "Microsoft.VSTS.Common.Severity": "3 - Medium",
                "System.IterationPath": "MyFirstProject",
            },
            "rev": 3,
            "id": 33,
            "_links": {
                "self": {
                    "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/revisions/3"
                },
                "workItemRevisions": {
                    "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/revisions"
                },
                "parent": {
                    "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33"
                },
            },
        },
    },
    "eventType": "workitem.updated",
    "detailedMessage": None,
    "createdDate": "2018-07-05T23:23:11.1935112   Z",
    "id": "cc349c85-6595-4939-9b69-f89480be6a26",
    "resourceVersion": "1.0",
    "notificationId": 2,
    "subscriptionId": "7405a600-6a25-48e6-81b6-1dde044783ad",
    "publisherId": "tfs",
    "message": None,
}
WORK_ITEM_UPDATED_STATUS: dict[str, Any] = {
    "resourceContainers": {
        "project": {
            "id": "c0bf429a-c03c-4a99-9336-d45be74db5a6",
            "baseUrl": "https://laurynsentry.visualstudio.com/",
        },
        "account": {
            "id": "90e9a854-eb98-4c56-ae1a-035a0f331dd6",
            "baseUrl": "https://laurynsentry.visualstudio.com/",
        },
        "collection": {
            "id": "80ded3e8-3cd3-43b1-9f96-52032624aa3a",
            "baseUrl": "https://laurynsentry.visualstudio.com/",
        },
    },
    "resource": {
        "revisedBy": {
            "displayName": "lauryn",
            "name": "lauryn <lauryn@sentry.io>",
            "url": "https://app.vssps.visualstudio.com/A90e9a854-eb98-4c56-ae1a-035a0f331dd6/_apis/Identities/21354f98-ab06-67d9-b974-5a54d992082e",
            "imageUrl": "https://laurynsentry.visualstudio.com/_api/_common/identityImage?id=21354f98-ab06-67d9-b974-5a54d992082e",
            "descriptor": "msa.MjEzNTRmOTgtYWIwNi03N2Q5LWI5NzQtNWE1NGQ5OTIwODJl",
            "_links": {
                "avatar": {
                    "href": "https://laurynsentry.visualstudio.com/_apis/GraphProfile/MemberAvatars/msa.MjEzNTRmOTgtYWIwNi03N2Q5LWI5NzQtNWE1NGQ5OTIwODJl"
                }
            },
            "uniqueName": "lauryn@sentry.io",
            "id": "21354f98-ab06-67d9-b974-5a54d992082e",
        },
        "revisedDate": "9999-01-01T00:00:00      Z",
        "url": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/updates/3",
        "fields": {
            "System.AuthorizedDate": {
                "newValue": "2018-07-05T23:23:09.493            Z",
                "oldValue": "2018-07-05T23:21:38.243            Z",
            },
            "System.State": {"oldValue": "New", "newValue": "Resolved"},
            "System.Watermark": {"newValue": 83, "oldValue": 82},
            "System.Rev": {"newValue": 3, "oldValue": 2},
            "System.RevisedDate": {
                "newValue": "9999-01-01T00:00:00            Z",
                "oldValue": "2018-07-05T23:23:09.493            Z",
            },
            "System.ChangedDate": {
                "newValue": "2018-07-05T23:23:09.493            Z",
                "oldValue": "2018-07-05T23:21:38.243            Z",
            },
        },
        "workItemId": 33,
        "rev": 3,
        "_links": {
            "self": {
                "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/updates/3"
            },
            "workItemUpdates": {
                "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/updates"
            },
            "html": {
                "href": "https://laurynsentry.visualstudio.com/web/wi.aspx?pcguid=80ded3e8-3cd3-43b1-9f96-52032624aa3a&id=33"
            },
            "parent": {
                "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33"
            },
        },
        "id": 3,
        "revision": {
            "url": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/revisions/3",
            "fields": {
                "System.AreaPath": "MyFirstProject",
                "System.WorkItemType": "Bug",
                "System.Reason": "New",
                "System.Title": "NotImplementedError:Visual Studio Team Services requires an organization_id",
                "Microsoft.VSTS.Common.Priority": 2,
                "System.CreatedBy": "lauryn <lauryn@sentry.io>",
                "Microsoft.VSTS.Common.StateChangeDate": "2018-07-05T23:21:25.847            Z",
                "System.CreatedDate": "2018-07-05T23:21:25.847            Z",
                "System.TeamProject": "MyFirstProject",
                "Microsoft.VSTS.Common.ValueArea": "Business",
                "System.State": "New",
                "System.Description": '<p><a href="https:            //lauryn.ngrok.io/sentry/internal/issues/196/">https:            //lauryn.ngrok.io/sentry/internal/issues/196/</a></p>\n<pre><code>NotImplementedError:Visual Studio Team Services requires an organization_id\n(57 additional frame(s) were not displayed)\n...\n  File &quot;sentry/tasks/base.py&quot;',
                "System.ChangedBy": "lauryn <lauryn@sentry.io>",
                "System.ChangedDate": "2018-07-05T23:23:09.493            Z",
                "Microsoft.VSTS.Common.Severity": "3 - Medium",
                "System.IterationPath": "MyFirstProject",
            },
            "rev": 3,
            "id": 33,
            "_links": {
                "self": {
                    "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/revisions/3"
                },
                "workItemRevisions": {
                    "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33/revisions"
                },
                "parent": {
                    "href": "https://laurynsentry.visualstudio.com/c0bf429a-c03c-4a99-9336-d45be74db5a6/_apis/wit/workItems/33"
                },
            },
        },
    },
    "eventType": "workitem.updated",
    "detailedMessage": None,
    "createdDate": "2018-07-05T23:23:11.1935112   Z",
    "id": "cc349c85-6595-4939-9b69-f89480be6a26",
    "resourceVersion": "1.0",
    "notificationId": 2,
    "subscriptionId": "7405a600-6a25-48e6-81b6-1dde044783ad",
    "publisherId": "tfs",
    "message": None,
}

WORK_ITEM_STATES = {
    "count": 5,
    "value": [
        {"name": "New", "color": "b2b2b2", "category": "Proposed"},
        {"name": "Active", "color": "007acc", "category": "InProgress"},
        {"name": "CustomState", "color": "5688E0", "category": "InProgress"},
        {"name": "Resolved", "color": "ff9d00", "category": "Resolved"},
        {"name": "Closed", "color": "339933", "category": "Completed"},
    ],
}

GET_PROJECTS_RESPONSE = """{
    "count": 1,
    "value": [{
        "id": "ac7c05bb-7f8e-4880-85a6-e08f37fd4a10",
        "name": "Fabrikam-Fiber-Git",
        "url": "https://jess-dev.visualstudio.com/_apis/projects/ac7c05bb-7f8e-4880-85a6-e08f37fd4a10",
        "state": "wellFormed",
        "revision": 16,
        "visibility": "private"
    }]
}"""
