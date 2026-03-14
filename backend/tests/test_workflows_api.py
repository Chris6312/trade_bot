def test_workflow_run_and_stage_can_be_recorded(client) -> None:
    run_response = client.post(
        "/api/v1/workflows/runs",
        json={
            "workflow_name": "premarket_cycle",
            "status": "running",
            "trigger_source": "manual",
            "notes": "phase2 smoke test",
        },
    )
    assert run_response.status_code == 201
    run_payload = run_response.json()
    assert run_payload["workflow_name"] == "premarket_cycle"
    run_id = run_payload["id"]

    stage_response = client.post(
        f"/api/v1/workflows/runs/{run_id}/stages",
        json={
            "stage_name": "universe",
            "status": "completed",
            "details": "Universe built",
        },
    )
    assert stage_response.status_code == 201
    stage_payload = stage_response.json()
    assert stage_payload["workflow_run_id"] == run_id
    assert stage_payload["status"] == "completed"

    run_detail_response = client.get(f"/api/v1/workflows/runs/{run_id}")
    assert run_detail_response.status_code == 200
    detail_payload = run_detail_response.json()
    assert len(detail_payload["stages"]) == 1
    assert detail_payload["stages"][0]["stage_name"] == "universe"
