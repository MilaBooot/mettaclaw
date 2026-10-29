!(import! &self (library OmegaClaw-Core ./plugins/openclaw/openclaw.py))
!(import! &self (library OmegaClaw-Core ./plugins/openclaw/subagents.py))

(= (openClawEnabled) (empty))
(= (openClawURL) (empty))
(= (openClawAgent) (empty))
(= (subagentStorePath) (empty))

(= (loadOmegaClawPlugin)
    (progn
        ; Enable or disable the integration.
        (configure openClawEnabled disabled)
        ; OpenClaw Gateway base URL, http://... or https://...
        ; In Docker this is only a fallback: the real target and its token
        ; are set at container start (openclaw_url=, OMEGACLAW_OPENCLAW_TOKEN)
        ; and injected by the local Nginx proxy. See plugins/openclaw/README.md.
        (configure openClawURL "")
        ; OpenClaw agent name. "main" by default
        (configure openClawAgent "main")
        ; One shared SQLite store for specialist sessions, runs, and messages.
        (configure subagentStorePath "./memory/subagent_sessions.sqlite3")
        (if (== (openClawEnabled) enabled)
            (if (== (openClawURL) "")
                (Error
                    (_loadOmegaClawPlugin)
                    "OpenClaw integration is enabled, but openClawURL is not configured")
                (progn
                    (log INFO "openclaw-plugin" "OpenClaw integration is enabled")
                    (add-skill
                        delegate-task-to-openclaw-agent
                        "Delegate a self-contained task to an external OpenClaw agent in a new separate session. Returns an id immediately, the reply arrives later on its own as an OPENCLAW_RESULT line."
                        (task_in_quotes))
                    (add-skill
                        delegate-task-to-subagent
                        "Delegate a bounded task to the best specialist capability (research, coding, or review). Pass only relevant context as text or a JSON object. Returns agent/session/run ids immediately; a compact SUBAGENT_RESULT arrives later."
                        (task_in_quotes capability_in_quotes relevant_context_in_quotes))
                    (add-skill
                        delegate-task-to-specific-subagent
                        "Delegate a bounded task to an explicit research-agent, coding-agent, or reviewer-agent. Pass only relevant context as text or a JSON object."
                        (task_in_quotes agent_id_in_quotes relevant_context_in_quotes))
                    (add-skill
                        resume-subagent-session
                        "Continue an existing subagent session with a new bounded goal and a new run. Pass the session id returned by the earlier delegation."
                        (session_id_in_quotes task_in_quotes relevant_context_in_quotes))
                    (add-skill
                        inspect-subagent-session
                        "Inspect one persistent subagent session and its recent run statuses without exposing the worker's private context or transcript."
                        (session_id_in_quotes))
                    (add-skill
                        dispose-subagent-session
                        "Dispose one idle subagent session. Pass false to retain run metadata while deleting private messages and continuation state, or true to purge the complete session."
                        (session_id_in_quotes purge_true_or_false))
                    (add-skill
                        cleanup-subagent-scope
                        "Dispose every idle subagent session owned by a workflow or space scope. Pass true to purge complete records during scope cleanup."
                        (scope_id_in_quotes purge_true_or_false))
                    (add-prompt-extension
                        subagent-coordination
                        "SUBAGENT COORDINATION: When a subagent delegation is accepted, tell the user which agent was selected and include its session and run ids. When a new SUBAGENT_RESULT appears in history, report its final status and summary once. A timed_out result is unfinished work: inspect possible partial effects, then decide whether one smaller, safer retry is appropriate; never blindly repeat a side-effecting task. Use inspect-subagent-session when the user asks for status. Do not expose stored worker prompts, raw replies, or intermediate reasoning.")
                    (add-heartbeat-listener
                        openclaw
                        (|-> ($iter) (openclaw-collect-results $iter)))
                    (add-heartbeat-listener
                        subagents
                        (|-> ($iter) (subagent-collect-results $iter)))))
            (log INFO "openclaw-plugin" "OpenClaw integration is disabled"))))

(= (delegate-task-to-openclaw-agent $message)
    (py-call (
        openclaw.send
        $message
        (openClawURL)
        (openClawAgent)
    )))

(= (delegate-task-to-subagent $task $capability $context)
    (py-call (
        subagents.delegate
        $task
        $capability
        $context
        (openClawURL)
        (subagentStorePath)
    )))

(= (delegate-task-to-specific-subagent $task $agent-id $context)
    (py-call (
        subagents.delegate_explicit
        $task
        $agent-id
        $context
        (openClawURL)
        (subagentStorePath)
    )))

(= (resume-subagent-session $session-id $task $context)
    (py-call (
        subagents.resume
        $session-id
        $task
        $context
        (openClawURL)
        (subagentStorePath)
    )))

(= (inspect-subagent-session $session-id)
    (py-call (
        subagents.inspect_session
        $session-id
        (subagentStorePath)
    )))

(= (dispose-subagent-session $session-id $purge)
    (py-call (
        subagents.dispose_session
        $session-id
        $purge
        (subagentStorePath)
    )))

(= (cleanup-subagent-scope $scope-id $purge)
    (py-call (
        subagents.dispose_scope
        $scope-id
        $purge
        (subagentStorePath)
    )))

; Delegations run off the agent loop, so their replies are picked up here once
; per iteration and appended to the history, which - unlike a prompt extension
; or LAST_SKILL_USE_RESULTS - also holds them while the agent is idle. Reading
; the Python side is the only safe direction: the worker threads never touch
; the atomspace.
;
; append-file rather than appendToHistory/library: this plugin's own
; definitions live in the plugin's own MeTTa space (src/plugin.metta),
; library's file-spec resolves against whichever space an
; evaluation started from - it does not find the OmegaClaw-Core alias
; reached this way. append-file takes a plain path and has no such
; dependency, so the path is built with projectRootDirectory/joinPath
; (same as pluginWorkflowInstructionsDir in workflow.metta) instead of
; going through library.
(= (openclaw-collect-results $iteration)
    (let $results (repr (py-call (openclaw.take_completed)))
        (if (> (string_length $results) 0)
            (append-file
                (joinPath ((projectRootDirectory) "memory" "history.metta"))
                (swrite ((get_time_as_string) (newline) $results (newline))))
            ())))

(= (subagent-collect-results $iteration)
    (py-call (
        subagents.deliver_completed
        (subagentStorePath)
        (joinPath ((projectRootDirectory) "memory" "history.metta"))
    )))
