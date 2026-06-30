from main import app


def test_system_and_insights_routes_are_registered():
    paths = set(app.openapi()["paths"])

    assert "/api/v1/ping" in paths
    assert "/api/v1/status" in paths
    assert "/api/v1/feed" in paths
    assert "/api/v1/feeds" in paths
    assert "/api/v1/metrics" in paths
    assert "/api/v1/metrics/cost" in paths
    assert "/api/v1/admin/tasks" in paths
    assert "/api/v1/insights/heatmap" in paths
    assert "/api/v1/insights/timeline" in paths
    assert "/api/v1/insights/topic_tree" in paths
    assert "/api/v1/insights/trending" in paths
    assert "/api/v1/research" in paths
    assert "/api/v1/briefing" in paths
    assert "/api/v1/briefing/refine" in paths
    assert "/api/v1/briefing/refine/{session_id}" in paths
    assert "/api/v1/boards" in paths
    assert "/api/v1/boards/wizard" in paths
    assert "/api/v1/boards/wizard/preview" in paths
    assert "/api/v1/boards/wizard/fix-feeds" in paths
    assert "/api/v1/boards/{slug}/sources/discover" in paths
    assert "/api/v1/boards/{slug}/sources/{source_id}/alternatives" in paths
    assert "/api/v1/summary" in paths
    assert "/api/v1/catchup/status" in paths
    assert "/api/v1/catchup" in paths
    assert "/api/v1/history" in paths
    assert "/api/v1/history/weekly_insight" in paths
    assert "/api/v1/history/weekly_report" in paths
    assert "/api/v1/cache" in paths
    assert "/api/v1/persona" in paths
    assert "/api/v1/persona/{persona_id}" in paths
    assert "/api/v1/feedback/interest-options" in paths
    assert "/api/v1/feedback/save-reason" in paths
    assert "/api/v1/articles/read" in paths
    assert "/api/v1/persona/inferred" in paths
    assert "/api/v1/persona/training" in paths
    assert "/api/v1/preferences" in paths
    assert "/api/v1/saved" in paths
    assert "/api/v1/saved/urls" in paths
    assert "/api/v1/silent-mode/status" in paths
    assert "/api/v1/silent-mode/run" in paths
    assert "/api/v1/sources/test" in paths
    assert "/api/v1/sources/test_all" in paths
    assert "/api/v1/sources/dashboard" in paths
    assert "/api/v1/sources/coverage" in paths
