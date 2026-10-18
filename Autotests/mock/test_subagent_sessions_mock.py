"""Docker integration test for persistent specialist sessions."""

import json

from helpers import Checker, dexec, make_prompt, wait_for_history_keyword, wait_for_skill_call


RESULT_TIMEOUT = 60
DB_PATH = "/PeTTa/repos/OmegaClaw-Core/memory/subagent_sessions.sqlite3"


def _read_json(path):
    return json.loads(dexec("cat", path).stdout.strip())


def _database_snapshot(session_id):
    script = """
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.row_factory = sqlite3.Row
session_id = sys.argv[2]
session = dict(db.execute(
    'select * from subagent_sessions where session_id = ?', (session_id,)
).fetchone())
runs = [dict(row) for row in db.execute(
    'select * from subagent_runs where session_id = ? order by started_at, run_id',
    (session_id,),
)]
messages = [dict(row) for row in db.execute(
    'select * from subagent_messages where session_id = ? order by created_at, message_id',
    (session_id,),
)]
print(json.dumps({'session': session, 'runs': runs, 'messages': messages}))
"""
    result = dexec("python3", "-c", script, DB_PATH, session_id)
    return json.loads(result.stdout.strip())


def test_subagent_new_session_and_resume_mock(llm, comm, gateway):
    with Checker("persistent subagent new session and resume") as c:
        print(f"\n=== OmegaClaw: persistent subagent mock (run-id {c.run_id}) ===", flush=True)
        first_path = f"/tmp/subagent_first_{c.run_id}.json"
        second_path = f"/tmp/subagent_resume_{c.run_id}.json"
        bounded_marker = f"BOUNDED-{c.run_id}"

        c.step("delegate a bounded research task through the Omega skill")
        prompt = make_prompt(c.run_id, "Use the persistent research specialist.")
        llm.set_answer(
            request=prompt,
            response=(
                f'(metta (write-file "{first_path}" '
                f'(delegate-task-to-subagent "Research session persistence" "research" '
                f'"Only inspect {bounded_marker}")))\n'
                f'(send "Persistent subagent accepted {c.run_id}")'
            ),
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver the new-session prompt")
        if not wait_for_skill_call(
            c.run_id, "send", timeout=30, arg_substr="Persistent subagent accepted"
        ):
            c.fail("send", "Omega did not stay responsive during delegation")

        accepted = _read_json(first_path)
        if accepted.get("status") != "accepted":
            c.fail("acceptance", f"unexpected result: {accepted}")
        if accepted.get("agent_id") != "research-agent":
            c.fail("selector", f"research did not select research-agent: {accepted}")
        c.ok("selector", "research capability selected research-agent")

        if not wait_for_history_keyword(
            c.run_id,
            [
                "SUBAGENT_RESULT agent=research-agent",
                f"session={accepted['session_id']}",
                f"run={accepted['run_id']}",
                "status=completed",
            ],
            timeout=RESULT_TIMEOUT,
            require_all=True,
        ):
            c.fail("result", "compact SUBAGENT_RESULT did not reach Omega history")
        c.ok("result", "Omega received the compact specialist result")

        first_requests = gateway.recorder.authorized_requests()
        if len(first_requests) != 1:
            c.fail("gateway", f"expected one Gateway request, got {len(first_requests)}")
        first_request = first_requests[0]
        if first_request["agent"] != "research-agent":
            c.fail("gateway", f"wrong OpenClaw target: {first_request['agent']}")
        if bounded_marker not in first_request["input"]:
            c.fail("context", "bounded context did not reach the specialist")
        if f"REQ-{c.run_id}" in first_request["input"]:
            c.fail("isolation", "Omega's outer prompt leaked into specialist context")
        if first_request["previous_response_id"] is not None:
            c.fail("continuation", "new session unexpectedly supplied previous_response_id")
        c.ok("isolation", "Gateway received only the projected worker context")

        first_db = _database_snapshot(accepted["session_id"])
        if first_db["session"]["agent_id"] != "research-agent":
            c.fail("database", f"wrong session owner: {first_db['session']}")
        if len(first_db["runs"]) != 1 or len(first_db["messages"]) != 2:
            c.fail("database", f"unexpected persisted state: {first_db}")
        c.ok("database", "session, run, projected prompt, and raw reply were persisted")

        c.step("resume the same session and create a second run")
        prompt = make_prompt(c.run_id + 1, "Resume the persistent research specialist.")
        llm.set_answer(
            request=prompt,
            response=(
                f'(metta (write-file "{second_path}" '
                f'(resume-subagent-session "{accepted["session_id"]}" '
                f'"Verify the persisted continuation" "Only verify {bounded_marker}")))\n'
                f'(send "Persistent subagent resumed {c.run_id}")'
            ),
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver the resume prompt")
        if not wait_for_skill_call(
            c.run_id, "send", timeout=30, arg_substr="Persistent subagent resumed"
        ):
            c.fail("send", "Omega did not acknowledge the resumed run")

        resumed = _read_json(second_path)
        if resumed.get("session_id") != accepted["session_id"]:
            c.fail("resume", f"resume changed session: {accepted}, {resumed}")
        if resumed.get("run_id") == accepted["run_id"]:
            c.fail("resume", f"resume reused run id: {resumed}")
        if not wait_for_history_keyword(
            c.run_id,
            [f"session={resumed['session_id']}", f"run={resumed['run_id']}"],
            timeout=RESULT_TIMEOUT,
            require_all=True,
        ):
            c.fail("resume", "resumed compact result did not reach history")

        requests = gateway.recorder.authorized_requests()
        if len(requests) != 2:
            c.fail("gateway", f"expected two Gateway requests, got {len(requests)}")
        if requests[1]["previous_response_id"] != requests[0]["response_id"]:
            c.fail("continuation", f"resume did not continue first response: {requests}")
        c.ok("continuation", "resume supplied the first run's previous_response_id")

        final_db = _database_snapshot(accepted["session_id"])
        if len(final_db["runs"]) != 2:
            c.fail("runs", f"expected two persisted runs: {final_db['runs']}")
        if len(final_db["messages"]) != 4:
            c.fail("messages", f"expected four persisted messages: {final_db['messages']}")
        c.ok("runs", "same session now owns two distinct persisted runs")
        c.done()
