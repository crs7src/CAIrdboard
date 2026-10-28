from app.main import app

EXPECTED = """
delete /api/ai/providers/{provider_id}/credentials
delete /api/cards/{key}/feedback/comments/{comment_id}
delete /api/cards/{key}/test
delete /api/cards/{key}/test/approval
delete /api/cards/{key}/test/config
delete /api/projects/{key}
delete /api/repo-hosts/{project}
delete /api/skills/{step}
delete /api/test-configs/{project}
get /api/ai-config
get /api/ai/providers
get /api/ai/providers/{provider_id}/check
get /api/cards
get /api/cards/{key}
get /api/cards/{key}/changes
get /api/cards/{key}/feedback
get /api/cards/{key}/implementation
get /api/cards/{key}/merge-request
get /api/cards/{key}/merge-request/defaults
get /api/cards/{key}/plan
get /api/cards/{key}/review
get /api/cards/{key}/test
get /api/cards/{key}/test/approval
get /api/cards/{key}/test/config
get /api/fs/dirs
get /api/github/status
get /api/gitlab/status
get /api/implementations
get /api/jira/status
get /api/merge-requests
get /api/plans
get /api/projects
get /api/projects/{key}
get /api/repo-hosts
get /api/repo-hosts/{project}
get /api/repo-hosts/{project}/check
get /api/reviews
get /api/skills
get /api/test-approvals
get /api/test-configs
get /api/test-configs/{project}
get /api/tests
post /api/cards/{key}/feedback/comments
post /api/cards/{key}/feedback/submit
post /api/cards/{key}/implementation
post /api/cards/{key}/merge-request
post /api/cards/{key}/plan
post /api/cards/{key}/plan/approve
post /api/cards/{key}/plan/reject
post /api/cards/{key}/review
post /api/cards/{key}/test
post /api/cards/{key}/test/feedback
post /api/cards/{key}/test/problem
post /api/projects
put /api/ai-config
put /api/ai/default
put /api/ai/providers/{provider_id}/credentials
put /api/cards/{key}/feedback/comments/{comment_id}
put /api/cards/{key}/test/approval
put /api/github/credentials
put /api/gitlab/credentials
put /api/jira/credentials
put /api/projects/{key}
put /api/repo-hosts/{project}
put /api/skills/{step}
put /api/test-configs/{project}
""".strip().splitlines()


def test_every_route_is_registered():
    actual = sorted(
        f"{method} {path}"
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    )
    assert actual == sorted(EXPECTED)
