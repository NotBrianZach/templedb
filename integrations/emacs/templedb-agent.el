;;; templedb-agent.el --- Temple Agent: native AI in Emacs -*- lexical-binding: t; -*-
;;
;; Author: Zach Abel
;; Package-Requires: ((emacs "28.1"))
;;
;;; Commentary:
;;
;; Temple Agent -- Claude Code inside Emacs, but native.
;; Uses TempleDB for memory, Org for display, JSON-lines for protocol.
;;
;; Entry point: M-x templedb-agent-new or SPC a T A n

;;; Code:

(require 'json)
(require 'org)

;;;; Configuration

(defgroup templedb-agent nil
  "Temple Agent: native AI in Emacs."
  :prefix "templedb-agent-"
  :group 'templedb)

(defcustom templedb-agent-executable
  (or (executable-find "templedb")
      (expand-file-name "~/templeDB/templedb")
      "templedb")
  "Path to the templedb executable."
  :type 'string
  :group 'templedb-agent)

(defcustom templedb-agent-default-provider "claude-code"
  "Default AI provider for new sessions."
  :type '(choice (const "fake") (const "claude-code"))
  :group 'templedb-agent)

;;;; State

(defvar-local templedb-agent--session-id nil "Current session ID.")
(defvar-local templedb-agent--run-id nil "Current run ID.")
(defvar-local templedb-agent--status "created" "Current session status.")
(defvar-local templedb-agent--project nil "Primary project slug.")
(defvar-local templedb-agent--projects nil "List of project slugs in context.")
(defvar-local templedb-agent--context-config nil
  "Context config per project. Alist of (slug . items-alist).")
(defvar-local templedb-agent--project-stats nil
  "Cached project stats. Alist of (slug . plist) with :files :commits :envs.")
(defvar-local templedb-agent--provider nil "Provider name.")
(defvar-local templedb-agent--process nil "Agent serve process.")
(defvar-local templedb-agent--request-id 0 "Request ID counter.")
(defvar-local templedb-agent--pending-requests nil "Pending (id . callback) alist.")
(defvar-local templedb-agent--partial-line "" "Incomplete JSON line.")
(defvar-local templedb-agent--streaming-text "" "Accumulated streaming text.")
(defvar-local templedb-agent--streaming-marker nil "Streaming insert marker.")
(defvar-local templedb-agent--now-text "" "Now section text.")

;;;; Process management

(defun templedb-agent--start-process ()
  "Start the agent serve process."
  (when (and templedb-agent--process (process-live-p templedb-agent--process))
    (delete-process templedb-agent--process))
  (let ((process-environment (append '("PYTHONDONTWRITEBYTECODE=1") process-environment))
        (buf (current-buffer))
        (stderr-buf (get-buffer-create "*temple-agent-stderr*")))
    (setq templedb-agent--process
          (make-process
           :name (format "temple-agent-%s" (or templedb-agent--session-id "new"))
           :buffer (generate-new-buffer " *temple-agent-proc*")
           :command (list templedb-agent-executable "ai" "agent" "serve" "--stdio")
           :connection-type 'pipe
           :noquery t
           :stderr stderr-buf
           :filter (lambda (proc output)
                     (templedb-agent--process-filter buf proc output))
           :sentinel (lambda (proc event)
                       (templedb-agent--process-sentinel buf proc event)))))
  templedb-agent--process)

(defun templedb-agent--process-filter (agent-buf _proc output)
  "Handle output from the agent process, parsing JSON lines."
  (when (buffer-live-p agent-buf)
    (with-current-buffer agent-buf
      (setq templedb-agent--partial-line
            (concat templedb-agent--partial-line output))
      (let ((lines (split-string templedb-agent--partial-line "\n")))
        (setq templedb-agent--partial-line (car (last lines)))
        (dolist (line (butlast lines))
          (let ((trimmed (string-trim line)))
            (when (and (not (string-empty-p trimmed))
                       (eq (aref trimmed 0) ?\{))
              (condition-case err
                  (let ((msg (json-read-from-string trimmed)))
                    (templedb-agent--handle-message msg))
                (error
                 (message "Temple Agent: JSON parse error: %s" err))))))))))

(defun templedb-agent--process-sentinel (agent-buf _proc event)
  "Handle process exit."
  (when (buffer-live-p agent-buf)
    (with-current-buffer agent-buf
      (when (string-match-p "\\(finished\\|exited\\|killed\\)" event)
        (setq templedb-agent--process nil)
        (let ((stderr (when-let ((sb (get-buffer "*temple-agent-stderr*")))
                        (with-current-buffer sb (string-trim (buffer-string))))))
          (templedb-agent--set-now
           (if (and stderr (not (string-empty-p stderr)))
               (format "Process ended: %s" (car (split-string stderr "\n")))
             (format "Process ended (%s)" (string-trim event))))
          (templedb-agent--set-status "interrupted"))))))

(defun templedb-agent--send (method params &optional callback)
  "Send a JSON-lines request to the agent process."
  (unless (and templedb-agent--process (process-live-p templedb-agent--process))
    (templedb-agent--start-process))
  (cl-incf templedb-agent--request-id)
  (let ((id templedb-agent--request-id)
        (request `((id . ,templedb-agent--request-id)
                   (method . ,method)
                   (params . ,params))))
    (when callback
      (push (cons id callback) templedb-agent--pending-requests))
    (process-send-string templedb-agent--process (concat (json-encode request) "\n"))
    id))

;;;; Message handling

(defun templedb-agent--handle-message (msg)
  "Handle a parsed JSON message from the agent process."
  (let ((id (alist-get 'id msg))
        (method (alist-get 'method msg))
        (result (alist-get 'result msg))
        (error-msg (alist-get 'error msg)))
    (cond
     (id
      (let ((callback (alist-get id templedb-agent--pending-requests)))
        (setq templedb-agent--pending-requests
              (assq-delete-all id templedb-agent--pending-requests))
        (when callback
          (if error-msg
              (progn
                (message "Temple Agent error: %s" error-msg)
                (templedb-agent--set-now (format "Error: %s" error-msg)))
            (funcall callback result)))))
     ((equal method "event")
      (templedb-agent--handle-event (alist-get 'params msg))))))

(defun templedb-agent--handle-event (event)
  "Handle a streaming event from the agent."
  (let ((type (alist-get 'type event))
        (summary (alist-get 'summary event))
        (data (alist-get 'data event)))
    (pcase type
      ("run.started"
       (setq templedb-agent--run-id (alist-get 'run_id event))
       (templedb-agent--set-now (or summary "Working..."))
       (templedb-agent--set-status "running"))
      ("run.completed"
       (templedb-agent--set-now "Ready")
       (templedb-agent--set-status "waiting")
       (templedb-agent--finalize-streaming))
      ("run.failed"
       (templedb-agent--set-now (format "Failed: %s" (or summary "unknown error")))
       (templedb-agent--set-status "failed")
       (templedb-agent--finalize-streaming))
      ("run.interrupted"
       (templedb-agent--set-now "Interrupted")
       (templedb-agent--set-status "interrupted")
       (templedb-agent--finalize-streaming))
      ("assistant.started"
       (templedb-agent--set-now "Generating response...")
       (templedb-agent--start-streaming))
      ("assistant.delta"
       (when-let ((text (alist-get 'text data)))
         (templedb-agent--append-streaming text)))
      ("assistant.completed"
       (templedb-agent--set-now "Response complete"))
      ("tool.started"
       (templedb-agent--set-now (or summary "Running tool..."))
       (templedb-agent--insert-rich-tool summary data "RUNNING"))
      ("tool.completed"
       (templedb-agent--complete-rich-tool summary data "DONE"))
      ("tool.failed"
       (templedb-agent--complete-rich-tool summary data "FAILED"))
      ("provider.rate_limited"
       (templedb-agent--set-now "Rate limited. Waiting..."))
      ("provider.login_required"
       (templedb-agent--set-now "Login required. Run: claude auth login"))
      ("service.recovered"
       (message "Temple Agent: %s" (or summary "Sessions recovered"))))))

;;;; Org buffer rendering

(defun templedb-agent--render-buffer ()
  "Render the full agent Org buffer."
  (let ((inhibit-read-only t))
    (erase-buffer)
    (insert (format "#+TITLE: Temple Agent\n"))
    (insert (format "#+TDB_SESSION_ID: %s\n" (or templedb-agent--session-id "")))
    (insert (format "#+TDB_PROJECT: %s\n" (or templedb-agent--project "")))
    (insert (format "#+TDB_STATUS: %s\n\n" templedb-agent--status))

    ;; Guide (starts collapsed)
    (insert "* Guide\n")
    (insert "Temple Agent -- Claude Code inside Emacs.\n")
    (insert "Type your message under *Next Prompt*, then press =C-c C-c= to send.\n\n")
    (insert "| Section        | Purpose                                    | Editable |\n")
    (insert "|----------------+--------------------------------------------+----------|\n")
    (insert "| Now            | What Claude is currently doing              | no       |\n")
    (insert "| Goal           | Session goal -- sent to Claude as guidance  | yes      |\n")
    (insert "| Context        | Projects and data sent with each message    | toggle   |\n")
    (insert "| Conversation   | Message history and tool activity           | no       |\n")
    (insert "| Next Prompt    | Your next message to Claude                 | yes      |\n")
    (insert "| Notes          | Persistent notes (saved to DB)              | yes      |\n")
    (insert "| Scratch        | Scratch space (not sent)                    | yes      |\n\n")
    (insert "| Key            | Action                                     |\n")
    (insert "|----------------+--------------------------------------------|\n")
    (insert "| =C-c C-c=      | Send message                               |\n")
    (insert "| =C-c C-k=      | Cancel current run                         |\n")
    (insert "| =C-c C-r=      | Resume interrupted run                     |\n")
    (insert "| =, x a=        | Add project to context                     |\n")
    (insert "| =, x r=        | Remove project from context                |\n")
    (insert "| =, x t=        | Toggle context item                        |\n")
    (insert "| =, x b=        | Add current buffer to context              |\n")
    (insert "| =, x v=        | Add selected region to context             |\n")
    (insert "| =, i=          | Send guidance while Claude works           |\n")
    (insert "| =, g=          | Refresh buffer from database               |\n")
    (insert "| =, s n=        | New session                                |\n")
    (insert "| =, s s=        | Switch session                             |\n")
    (insert "| =, s f=        | Fork session                               |\n")
    (insert "| =, s q=        | Close session                              |\n")
    (insert "| =, ?=          | Debug info (process, stderr, pending)      |\n")
    (insert "| =, K=          | Kill stuck process                         |\n")
    (insert "| =TAB=          | Fold/unfold section                        |\n\n")

    ;; Now
    (insert "* Now\n\n")
    (insert (or templedb-agent--now-text "Ready") "\n\n")

    ;; Goal (editable, sent to Claude)
    (insert "* Goal\n\n")
    (insert "Set your goal here. It is sent to Claude with every message to keep the conversation focused.\n\n")

    ;; Context basket
    (insert "* Context\n\n")
    (templedb-agent--insert-context-basket)
    (insert "\n")
    (insert "* Conversation\n\n")
    (insert "* Next Prompt\n\n\n")
    (insert "* Notes\n\n\n")
    (insert "* Scratch\n\n\n")

    ;; Collapse the Guide section by default
    (goto-char (point-min))
    (when (re-search-forward "^\\* Guide" nil t)
      (org-cycle))))

(defun templedb-agent--set-now (text)
  "Update the Now section."
  (setq templedb-agent--now-text text)
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* Now\n\n" nil t)
      (let ((start (point))
            (end (if (re-search-forward "^\\* " nil t)
                     (match-beginning 0) (point-max))))
        (let ((inhibit-read-only t))
          (delete-region start end)
          (goto-char start)
          (insert text "\n\n"))))))

(defun templedb-agent--set-status (status)
  "Update the session status."
  (setq templedb-agent--status status)
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^#\\+TDB_STATUS: .*$" nil t)
      (let ((inhibit-read-only t))
        (replace-match (format "#+TDB_STATUS: %s" status))))))

(defun templedb-agent--insert-conversation-entry (role text)
  "Insert a conversation entry under * Conversation."
  (save-excursion
    (goto-char (point-min))
    (if (re-search-forward "^\\* Next Prompt" nil t)
        (progn
          (forward-line -1)
          (let ((inhibit-read-only t))
            (insert (format "\n** %s\n\n%s\n" (capitalize role) text))))
      (goto-char (point-min))
      (when (re-search-forward "^\\* Conversation\n" nil t)
        (goto-char (if (re-search-forward "^\\* " nil t)
                       (match-beginning 0) (point-max)))
        (let ((inhibit-read-only t))
          (insert (format "\n** %s\n\n%s\n" (capitalize role) text)))))))

(defun templedb-agent--start-streaming ()
  "Prepare for streaming assistant response."
  (setq templedb-agent--streaming-text "")
  (save-excursion
    (goto-char (point-min))
    (if (re-search-forward "^\\* Next Prompt" nil t)
        (progn
          (forward-line -1)
          (let ((inhibit-read-only t))
            (insert "\n** Assistant\n\n")
            (setq templedb-agent--streaming-marker (point-marker))))
      (goto-char (point-max))
      (let ((inhibit-read-only t))
        (insert "\n** Assistant\n\n")
        (setq templedb-agent--streaming-marker (point-marker))))))

(defun templedb-agent--append-streaming (text)
  "Append TEXT to the streaming assistant response.
Uses `with-undo-amalgamate' so all streaming chunks become one undo entry."
  (setq templedb-agent--streaming-text
        (concat templedb-agent--streaming-text text))
  (when (and templedb-agent--streaming-marker
             (marker-buffer templedb-agent--streaming-marker))
    (with-undo-amalgamate
      (save-excursion
        (goto-char templedb-agent--streaming-marker)
        (let ((inhibit-read-only t))
          (insert text)
          (set-marker templedb-agent--streaming-marker (point)))))))

(defun templedb-agent--finalize-streaming ()
  "Finalize the streaming response."
  (when templedb-agent--streaming-marker
    (save-excursion
      (goto-char templedb-agent--streaming-marker)
      (let ((inhibit-read-only t)) (insert "\n")))
    (set-marker templedb-agent--streaming-marker nil)
    (setq templedb-agent--streaming-marker nil))
  (setq templedb-agent--streaming-text ""))

;;; Rich tool display

(defun templedb-agent--insert-rich-tool (summary data status)
  "Insert a rich tool heading with input details.
Shows tool name, input as code block, status indicator."
  (let ((tool-name (alist-get 'tool_name data))
        (tool-input (alist-get 'tool_input data))
        (tool-id (alist-get 'tool_id data)))
    (with-undo-amalgamate
      (save-excursion
        (goto-char (point-min))
        (if (re-search-forward "^\\* Next Prompt" nil t)
            (forward-line -1)
          (goto-char (point-max)))
        (let ((inhibit-read-only t))
          (insert (format "\n** %s %s\n" status (or summary tool-name "tool")))
          (when (and tool-input (not (string-empty-p tool-input)))
            (let ((lang (cond
                         ((member tool-name '("Bash" "bash")) "shell")
                         ((member tool-name '("Edit" "edit")) "diff")
                         (t ""))))
              (insert (format "#+begin_src %s\n%s\n#+end_src\n"
                              lang
                              (templedb-agent--truncate-output tool-input 500))))))))))

(defun templedb-agent--complete-rich-tool (summary data new-status)
  "Update a tool heading to completed/failed and add output."
  (let ((tool-output (alist-get 'tool_output data))
        (duration (alist-get 'duration data)))
    (save-excursion
      (goto-char (point-max))
      ;; Find the matching RUNNING heading
      (when (re-search-backward
             (format "^\\*\\* RUNNING %s$"
                     (regexp-quote (or summary "")))
             nil t)
        (let ((inhibit-read-only t))
          ;; Update status with duration
          (let ((status-str (if duration
                                (format "%s %s (%.1fs)" new-status (or summary "") duration)
                              (format "%s %s" new-status (or summary "")))))
            (replace-match (format "** %s" status-str) t t))
          ;; Add output after the src block (or after heading if no src block)
          (forward-line 1)
          ;; Skip past any existing src block
          (when (looking-at "^#\\+begin_src")
            (re-search-forward "^#\\+end_src" nil t)
            (forward-line 1))
          ;; Insert output
          (when (and tool-output (not (string-empty-p tool-output)))
            (insert (format "#+begin_example\n%s\n#+end_example\n"
                            (templedb-agent--truncate-output tool-output 1000)))))))))

(defun templedb-agent--truncate-output (text max-len)
  "Truncate TEXT for display, showing line count if truncated."
  (if (<= (length text) max-len)
      text
    (let* ((truncated (substring text 0 max-len))
           (total-lines (length (split-string text "\n")))
           (shown-lines (length (split-string truncated "\n"))))
      (format "%s\n... +%d lines" truncated (- total-lines shown-lines)))))

(defun templedb-agent--restore-messages (messages)
  "Restore conversation from saved MESSAGES."
  (dolist (msg messages)
    (let ((role (alist-get 'role msg))
          (text (alist-get 'content_text msg)))
      (when (and role text (not (string-empty-p text)))
        (templedb-agent--insert-conversation-entry role text)))))

;;;; User commands

(defun templedb-agent--get-prompt-text ()
  "Get the text from the Next Prompt section."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* Next Prompt\n\n" nil t)
      (let ((start (point))
            (end (if (re-search-forward "^\\* " nil t)
                     (match-beginning 0) (point-max))))
        (string-trim (buffer-substring-no-properties start end))))))

(defun templedb-agent--clear-prompt ()
  "Clear the Next Prompt section."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* Next Prompt\n\n" nil t)
      (let ((start (point))
            (end (if (re-search-forward "^\\* " nil t)
                     (match-beginning 0) (point-max))))
        (let ((inhibit-read-only t))
          (delete-region start end)
          (goto-char start)
          (insert "\n"))))))

(defun templedb-agent-send ()
  "Send the message in Next Prompt to the agent."
  (interactive)
  (let ((text (templedb-agent--get-prompt-text)))
    (when (or (null text) (string-empty-p text))
      (user-error "No message to send. Type in the Next Prompt section"))
    ;; Auto-set goal from first message
    (templedb-agent--auto-goal-from-message text)
    (templedb-agent--insert-conversation-entry "user" text)
    (templedb-agent--clear-prompt)
    (if (equal templedb-agent--status "running")
        (templedb-agent--send
         "message.queue"
         `((session_id . ,templedb-agent--session-id)
           (content . ,text))
         (lambda (_result) (message "Message queued (Claude is working)")))
      (templedb-agent--send
       "message.send"
       `((session_id . ,templedb-agent--session-id)
         (content . ,text)
         (context . ,(templedb-agent--build-context-payload)))
       (lambda (_result) nil)))))

(defun templedb-agent-cancel ()
  "Cancel the current run."
  (interactive)
  (templedb-agent--send
   "run.cancel"
   `((session_id . ,templedb-agent--session-id))
   (lambda (_result) (message "Run cancelled"))))

(defun templedb-agent-resume ()
  "Resume an interrupted run."
  (interactive)
  (templedb-agent--send
   "run.resume"
   `((session_id . ,templedb-agent--session-id))
   (lambda (_result) nil)))

(defun templedb-agent-guide (guidance)
  "Send GUIDANCE to influence the current run."
  (interactive "sGuidance: ")
  (templedb-agent--insert-conversation-entry "user" (format "[Guidance] %s" guidance))
  (templedb-agent--send
   "message.send"
   `((session_id . ,templedb-agent--session-id)
     (content . ,(format "[Guidance] %s" guidance)))
   (lambda (_result) nil)))

(defun templedb-agent-refresh ()
  "Refresh the buffer from database state."
  (interactive)
  (templedb-agent--send
   "session.open"
   `((session_id . ,templedb-agent--session-id))
   (lambda (result)
     (let ((session (alist-get 'session result))
           (org-text (alist-get 'org result)))
       (setq templedb-agent--status (alist-get 'status session))
       (setq templedb-agent--project
             (or (alist-get 'project_slug session) templedb-agent--project))
       (setq templedb-agent--provider
             (or (alist-get 'provider_name session) templedb-agent--provider))
       (when org-text
         (let ((inhibit-read-only t) (pos (point)))
           (erase-buffer)
           (insert org-text)
           (goto-char (min pos (point-max)))))))))

;;;; Session management

(defun templedb-agent--project-slugs ()
  "Get list of project slugs."
  (condition-case nil
      (let ((output (with-temp-buffer
                      (call-process templedb-agent-executable nil t nil
                                    "project" "list")
                      (buffer-string))))
        (let (slugs)
          (dolist (line (split-string output "\n" t))
            (when (string-match "^\\([a-zA-Z0-9_-]+\\)" (string-trim line))
              (push (match-string 1 (string-trim line)) slugs)))
          (nreverse slugs)))
    (error nil)))

(defun templedb-agent--wait-and-create-session (buf &optional attempts)
  "Wait for the agent process to be ready, then create a session."
  (let ((n (or attempts 0)))
    (if (and (buffer-live-p buf)
             (with-current-buffer buf
               (and templedb-agent--process
                    (process-live-p templedb-agent--process))))
        (with-current-buffer buf
          (templedb-agent--send
           "session.create"
           `((provider . ,templedb-agent--provider)
             (project . ,templedb-agent--project))
           (lambda (result)
             (when (buffer-live-p buf)
               (with-current-buffer buf
                 (setq templedb-agent--session-id (alist-get 'id result))
                 (templedb-agent--render-buffer)
                 (templedb-agent--set-now "Ready")
                 (message "Temple Agent session %d created"
                          templedb-agent--session-id))))))
      (if (< n 10)
          (run-at-time 0.2 nil
                       (lambda ()
                         (templedb-agent--wait-and-create-session buf (1+ n))))
        (when (buffer-live-p buf)
          (with-current-buffer buf
            (templedb-agent--set-now "Failed to start agent process")))))))

;;;###autoload
(defun templedb-agent-new (project)
  "Start a new Temple Agent session for PROJECT."
  (interactive
   (list (completing-read "Project: " (templedb-agent--project-slugs) nil nil)))
  (let* ((buf-name (format "*Temple Agent: %s*" project))
         (buf (get-buffer-create buf-name)))
    (switch-to-buffer buf)
    (templedb-agent-mode)
    (setq templedb-agent--project project)
    (setq templedb-agent--projects (list project))
    (setq templedb-agent--context-config nil)
    (templedb-agent--ensure-context-config project)
    (setq templedb-agent--provider templedb-agent-default-provider)
    (templedb-agent--render-buffer)
    (templedb-agent--set-now "Starting agent...")
    (templedb-agent--start-process)
    (templedb-agent--wait-and-create-session buf)))

(defun templedb-agent--wait-and-open-session (buf session-id &optional attempts)
  "Wait for the agent process, then open a session."
  (let ((n (or attempts 0)))
    (if (and (buffer-live-p buf)
             (with-current-buffer buf
               (and templedb-agent--process
                    (process-live-p templedb-agent--process))))
        (with-current-buffer buf
          (templedb-agent--send
           "session.open"
           `((session_id . ,session-id))
           (lambda (result)
             (when (buffer-live-p buf)
               (with-current-buffer buf
                 (let ((session (alist-get 'session result))
                       (org-text (alist-get 'org result)))
                   (setq templedb-agent--project
                         (or (alist-get 'project_slug session) ""))
                   (setq templedb-agent--provider
                         (alist-get 'provider_name session))
                   (setq templedb-agent--status
                         (alist-get 'status session))
                   (if org-text
                       (let ((inhibit-read-only t))
                         (erase-buffer)
                         (insert org-text))
                     (templedb-agent--render-buffer))
                   (message "Temple Agent session %d opened (%s)"
                            session-id (alist-get 'status session))))))))
      (if (< n 10)
          (run-at-time 0.2 nil
                       (lambda ()
                         (templedb-agent--wait-and-open-session buf session-id (1+ n))))
        (when (buffer-live-p buf)
          (with-current-buffer buf
            (templedb-agent--set-now "Failed to start agent process")))))))

;;;###autoload
(defun templedb-agent-open (session-id)
  "Open an existing Temple Agent session by SESSION-ID."
  (interactive "nSession ID: ")
  (let* ((buf-name (format "*Temple Agent: #%d*" session-id))
         (buf (get-buffer-create buf-name)))
    (switch-to-buffer buf)
    (templedb-agent-mode)
    (setq templedb-agent--session-id session-id)
    (templedb-agent--render-buffer)
    (templedb-agent--set-now "Loading session...")
    (templedb-agent--start-process)
    (templedb-agent--wait-and-open-session buf session-id)))

;;;###autoload
(defun templedb-agent-list ()
  "List Temple Agent sessions."
  (interactive)
  (let ((output (with-temp-buffer
                  (call-process templedb-agent-executable nil t nil
                                "ai" "agent" "sessions")
                  (buffer-string))))
    (if (string-match-p "No agent sessions" output)
        (message "No agent sessions found.")
      (with-current-buffer (get-buffer-create "*Temple Agent Sessions*")
        (let ((inhibit-read-only t))
          (erase-buffer)
          (insert output))
        (special-mode)
        (display-buffer (current-buffer))))))

;;;###autoload
(defun templedb-agent-doctor ()
  "Check Temple Agent provider health."
  (interactive)
  (message "%s" (string-trim
                 (with-temp-buffer
                   (call-process templedb-agent-executable nil t nil
                                 "ai" "agent" "doctor"
                                 "--provider" templedb-agent-default-provider)
                   (buffer-string)))))

;;;###autoload
(defun templedb-agent-fork ()
  "Fork the current agent session."
  (interactive)
  (unless templedb-agent--session-id
    (user-error "No active session to fork"))
  (templedb-agent--send
   "session.fork"
   `((session_id . ,templedb-agent--session-id))
   (lambda (result)
     (templedb-agent-open (alist-get 'id result)))))

;;;###autoload
(defun templedb-agent-switch ()
  "Switch to a different agent session."
  (interactive)
  (let* ((output (with-temp-buffer
                   (call-process templedb-agent-executable nil t nil
                                 "ai" "agent" "sessions" "--json")
                   (buffer-string)))
         (sessions (condition-case nil (json-read-from-string output) (error nil))))
    (if (or (null sessions) (= (length sessions) 0))
        (message "No sessions to switch to")
      (let* ((choices (mapcar (lambda (s)
                                (format "%d: %s [%s]"
                                        (alist-get 'id s)
                                        (or (alist-get 'title s) "(untitled)")
                                        (alist-get 'status s)))
                              (append sessions nil)))
             (choice (completing-read "Session: " choices nil t))
             (id (string-to-number choice)))
        (templedb-agent-open id)))))

;;;; Context basket

(defvar templedb-agent--context-items
  '((project_prompt . "Project prompt (rules, workflow, MCP tools)")
    (recent_commits . "Recent commits")
    (file_tree      . "Full file tree")
    (schema         . "Language breakdown")
    (env            . "Environment")
    (selected_files . "Selected files (contents)"))
  "Available context item types and labels.")

(defvar templedb-agent--context-defaults
  '((project_prompt . t)
    (recent_commits . t)
    (file_tree      . nil)
    (schema         . nil)
    (env            . nil)
    (selected_files . nil))
  "Default toggle state for context items.")

(defun templedb-agent--ensure-context-config (slug)
  "Ensure SLUG has an entry in the context config."
  (unless (assoc slug templedb-agent--context-config)
    (push (cons slug (copy-alist templedb-agent--context-defaults))
          templedb-agent--context-config)))

(defun templedb-agent--query-project-stats (slug)
  "Query TempleDB for project stats. Returns plist with :files :lines :commits :envs :name.
Uses sqlite3 directly for speed (no process startup)."
  (or (cdr (assoc slug templedb-agent--project-stats))
      (condition-case nil
          (let* ((db-path (or (and (boundp 'templedb-db-path) templedb-db-path)
                              (expand-file-name "~/.local/share/templedb/templedb.sqlite")))
                 (sqlite3 (or (executable-find "sqlite3")
                              (car (file-expand-wildcards "/nix/store/*-sqlite-*-bin/bin/sqlite3"))
                              "sqlite3"))
                 (sql (format "SELECT
                    p.name,
                    (SELECT COUNT(*) FROM project_files WHERE project_id=p.id AND status='active') as files,
                    (SELECT COALESCE(SUM(lines_of_code),0) FROM project_files WHERE project_id=p.id) as lines,
                    (SELECT COUNT(*) FROM vcs_commits WHERE project_id=p.id) as commits,
                    (SELECT COUNT(*) FROM nix_environments WHERE project_id=p.id AND is_active=1) as envs,
                    (SELECT COUNT(*) FROM project_env_vars WHERE project_id=p.id) as vars
                  FROM projects p WHERE p.slug='%s'" slug))
                 (output (with-temp-buffer
                           (call-process sqlite3 nil t nil "-separator" "|" db-path sql)
                           (buffer-string)))
                 (parts (split-string (string-trim output) "|")))
            (when (>= (length parts) 6)
              (let ((stats (list :name (nth 0 parts)
                                 :files (string-to-number (nth 1 parts))
                                 :lines (string-to-number (nth 2 parts))
                                 :commits (string-to-number (nth 3 parts))
                                 :envs (string-to-number (nth 4 parts))
                                 :vars (string-to-number (nth 5 parts)))))
                (push (cons slug stats) templedb-agent--project-stats)
                stats)))
        (error nil))))

(defun templedb-agent--context-item-label (key stats)
  "Return an enriched label for context item KEY using STATS."
  (let ((files (or (plist-get stats :files) 0))
        (lines (or (plist-get stats :lines) 0))
        (commits (or (plist-get stats :commits) 0))
        (envs (or (plist-get stats :envs) 0))
        (vars (or (plist-get stats :vars) 0)))
    (pcase key
      ('project_prompt
       "Project prompt -- FUSE paths, MCP tools, workflow rules")
      ('recent_commits
       (format "Recent commits -- last 5 of %d total" commits))
      ('file_tree
       (format "Full file tree -- %d files, %s lines"
               files (templedb-agent--format-number lines)))
      ('schema
       "Language breakdown -- files and lines per language")
      ('env
       (if (> (+ envs vars) 0)
           (format "Environment -- %d envs, %d vars" envs vars)
         "Environment -- none configured"))
      ('selected_files
       "Selected files -- include full source of chosen files")
      (_ (or (cdr (assq key templedb-agent--context-items)) (symbol-name key))))))

(defun templedb-agent--format-number (n)
  "Format number N with K/M suffix."
  (cond
   ((>= n 1000000) (format "%.1fM" (/ n 1000000.0)))
   ((>= n 1000) (format "%.1fK" (/ n 1000.0)))
   (t (number-to-string n))))

(defun templedb-agent--query-detail (sql)
  "Run a quick SQL query against TempleDB, return lines."
  (condition-case nil
      (let* ((db-path (or (and (boundp 'templedb-db-path) templedb-db-path)
                          (expand-file-name "~/.local/share/templedb/templedb.sqlite")))
             (sqlite3 (or (executable-find "sqlite3")
                          (car (file-expand-wildcards "/nix/store/*-sqlite-*-bin/bin/sqlite3"))
                          "sqlite3")))
        (with-temp-buffer
          (call-process sqlite3 nil t nil "-separator" "|" db-path sql)
          (string-trim (buffer-string))))
    (error "")))

(defun templedb-agent--insert-context-basket ()
  "Insert the context basket with per-project Org sub-trees and inline previews."
  (let ((projects (or templedb-agent--projects
                      (when templedb-agent--project
                        (list templedb-agent--project)))))
    (if (not projects)
        (insert "(no projects -- use , x a to add one)\n")
      (dolist (slug projects)
        (templedb-agent--ensure-context-config slug)
        (let* ((items (cdr (assoc slug templedb-agent--context-config)))
               (stats (templedb-agent--query-project-stats slug))
               (name (or (plist-get stats :name) slug))
               (files (or (plist-get stats :files) 0))
               (lines (or (plist-get stats :lines) 0))
               (commits (or (plist-get stats :commits) 0))
               (envs (or (plist-get stats :envs) 0))
               (vars (or (plist-get stats :vars) 0)))

          ;; Project heading with properties
          (insert (format "** %s\n" name))
          (insert ":PROPERTIES:\n")
          (insert (format ":SLUG: %s\n" slug))
          (insert (format ":FILES: %d\n" files))
          (insert (format ":LINES: %s\n" (templedb-agent--format-number lines)))
          (insert (format ":COMMITS: %d\n" commits))
          (insert ":END:\n\n")

          ;; Each context item as a sub-heading with preview
          ;; --- Project Prompt ---
          (let ((val (alist-get 'project_prompt items)))
            (insert (format "*** %s Project Prompt\n"
                            (if val "ACTIVE" "OFF")))
            (insert "FUSE paths, MCP tools, workflow rules, vibe-style context.\n")
            (insert "Same prompt used by =templedb ai vibe start=.\n\n"))

          ;; --- Recent Commits ---
          (let ((val (alist-get 'recent_commits items)))
            (insert (format "*** %s Recent Commits (%d total)\n"
                            (if val "ACTIVE" "OFF") commits))
            (when (and val (> commits 0))
              (let ((output (templedb-agent--query-detail
                             (format "SELECT substr(commit_hash,1,8) || ' ' || substr(commit_message,1,60) || ' (' || commit_timestamp || ')'
                                      FROM vcs_commits WHERE project_id=(SELECT id FROM projects WHERE slug='%s')
                                      ORDER BY commit_timestamp DESC LIMIT 5" slug))))
                (when (not (string-empty-p output))
                  (dolist (line (split-string output "\n"))
                    (insert (format "- ~%s~\n" line)))))
              (insert "\n")))

          ;; --- File Tree ---
          (let ((val (alist-get 'file_tree items)))
            (insert (format "*** %s File Tree (%d files, %s lines)\n"
                            (if val "ACTIVE" "OFF")
                            files (templedb-agent--format-number lines)))
            (when val
              (let ((output (templedb-agent--query-detail
                             (format "SELECT DISTINCT
                                        CASE WHEN instr(file_path,'/')>0
                                             THEN substr(file_path,1,instr(file_path,'/')-1)
                                             ELSE file_path END as dir
                                      FROM project_files
                                      WHERE project_id=(SELECT id FROM projects WHERE slug='%s')
                                        AND status='active'
                                      ORDER BY dir LIMIT 20" slug))))
                (when (not (string-empty-p output))
                  (insert "Top-level:\n")
                  (dolist (dir (split-string output "\n"))
                    (insert (format "- =%s/=\n" dir)))
                  (insert "\n")))))

          ;; --- Language Breakdown ---
          (let ((val (alist-get 'schema items)))
            (insert (format "*** %s Language Breakdown\n"
                            (if val "ACTIVE" "OFF")))
            (when val
              (let ((output (templedb-agent--query-detail
                             (format "SELECT
                                CASE
                                  WHEN file_path LIKE '%%.py' THEN 'Python'
                                  WHEN file_path LIKE '%%.js' THEN 'JavaScript'
                                  WHEN file_path LIKE '%%.ts' OR file_path LIKE '%%.tsx' THEN 'TypeScript'
                                  WHEN file_path LIKE '%%.nix' THEN 'Nix'
                                  WHEN file_path LIKE '%%.el' THEN 'Emacs Lisp'
                                  WHEN file_path LIKE '%%.json' THEN 'JSON'
                                  WHEN file_path LIKE '%%.sql' THEN 'SQL'
                                  WHEN file_path LIKE '%%.css' THEN 'CSS'
                                  WHEN file_path LIKE '%%.html' THEN 'HTML'
                                  ELSE 'Other'
                                END || '|' || COUNT(*) || '|' || COALESCE(SUM(lines_of_code),0)
                              FROM project_files
                              WHERE project_id=(SELECT id FROM projects WHERE slug='%s') AND status='active'
                              GROUP BY 1 ORDER BY COUNT(*) DESC" slug))))
                (when (not (string-empty-p output))
                  (insert "| Language | Files | Lines |\n")
                  (insert "|----------+-------+-------|\n")
                  (dolist (line (split-string output "\n"))
                    (let ((cols (split-string line "|")))
                      (when (>= (length cols) 3)
                        (insert (format "| %s | %s | %s |\n"
                                        (nth 0 cols) (nth 1 cols) (nth 2 cols))))))
                  (insert "\n")))))

          ;; --- Environment ---
          (let ((val (alist-get 'env items)))
            (insert (format "*** %s Environment (%d envs, %d vars)\n"
                            (if val "ACTIVE" "OFF") envs vars))
            (when (and val (> (+ envs vars) 0))
              (when (> envs 0)
                (let ((output (templedb-agent--query-detail
                               (format "SELECT env_name || ': ' || COALESCE(description,'')
                                        FROM nix_environments
                                        WHERE project_id=(SELECT id FROM projects WHERE slug='%s') AND is_active=1" slug))))
                  (when (not (string-empty-p output))
                    (insert "Nix environments:\n")
                    (dolist (line (split-string output "\n"))
                      (insert (format "- %s\n" line))))))
              (when (> vars 0)
                (let ((output (templedb-agent--query-detail
                               (format "SELECT var_name || ': ' || COALESCE(description,'')
                                        FROM project_env_vars
                                        WHERE project_id=(SELECT id FROM projects WHERE slug='%s')
                                        ORDER BY var_name LIMIT 10" slug))))
                  (when (not (string-empty-p output))
                    (insert "Variables:\n")
                    (dolist (line (split-string output "\n"))
                      (insert (format "- =%s=\n" line))))))
              (insert "\n")))

          ;; --- Selected Files ---
          (let ((val (alist-get 'selected_files items)))
            (insert (format "*** %s Selected Files\n"
                            (if val "ACTIVE" "OFF")))
            (insert "Use =, x b= to add current buffer or =, x v= for selection.\n\n"))

          )))))

(defun templedb-agent--render-context-section ()
  "Re-render just the Context section in place."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* Context\n\n" nil t)
      (let ((start (point))
            (end (if (re-search-forward "^\\* " nil t)
                     (match-beginning 0) (point-max))))
        (let ((inhibit-read-only t))
          (delete-region start end)
          (goto-char start)
          (templedb-agent--insert-context-basket)
          (insert "\n"))))))

(defun templedb-agent--get-goal-text ()
  "Get the text from the Goal section."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* Goal\n\n" nil t)
      (let ((start (point))
            (end (if (re-search-forward "^\\* " nil t)
                     (match-beginning 0) (point-max))))
        (let ((text (string-trim (buffer-substring-no-properties start end))))
          ;; Filter out the placeholder text
          (if (string-match-p "^Set your goal here" text)
              nil
            (unless (string-empty-p text) text)))))))

(defun templedb-agent--set-goal (text)
  "Set the Goal section text."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* Goal\n\n" nil t)
      (let ((start (point))
            (end (if (re-search-forward "^\\* " nil t)
                     (match-beginning 0) (point-max))))
        (let ((inhibit-read-only t))
          (delete-region start end)
          (goto-char start)
          (insert text "\n\n"))))))

(defun templedb-agent--auto-goal-from-message (text)
  "Auto-set goal from first user message if goal is not already set."
  (unless (templedb-agent--get-goal-text)
    ;; Use first sentence or first 120 chars as goal
    (let ((goal (if (string-match "[.!?]\s" text)
                    (substring text 0 (1+ (match-beginning 0)))
                  (if (> (length text) 120)
                      (concat (substring text 0 120) "...")
                    text))))
      (templedb-agent--set-goal goal))))

(defun templedb-agent--build-context-payload ()
  "Build context payload from current config for sending to the service.
Includes goal text and per-project context items."
  (let ((projects-payload '())
        (goal (templedb-agent--get-goal-text)))
    (dolist (slug (or templedb-agent--projects
                      (when templedb-agent--project
                        (list templedb-agent--project))))
      (let* ((items (cdr (assoc slug templedb-agent--context-config)))
             (item-obj '()))
        (dolist (pair items)
          (push (cons (symbol-name (car pair)) (if (cdr pair) t :json-false))
                item-obj))
        (push `((slug . ,slug) (items . ,item-obj)) projects-payload)))
    (let ((payload `((projects . ,(vconcat (nreverse projects-payload))))))
      (when goal
        (push (cons 'goal goal) payload))
      payload)))

(defun templedb-agent-add-project (project)
  "Add PROJECT to the session context."
  (interactive
   (list (completing-read "Add project: " (templedb-agent--project-slugs) nil nil)))
  (unless (member project templedb-agent--projects)
    (push project templedb-agent--projects)
    (templedb-agent--ensure-context-config project)
    (templedb-agent--render-context-section)
    (message "Added %s to context" project)))

(defun templedb-agent-remove-project (project)
  "Remove PROJECT from the session context."
  (interactive
   (list (completing-read "Remove project: " templedb-agent--projects nil t)))
  (setq templedb-agent--projects (delete project templedb-agent--projects))
  (setq templedb-agent--context-config
        (assoc-delete-all project templedb-agent--context-config))
  (when (equal project templedb-agent--project)
    (setq templedb-agent--project (car templedb-agent--projects)))
  (templedb-agent--render-context-section)
  (message "Removed %s from context" project))

(defun templedb-agent-toggle-context-item ()
  "Toggle a context item on/off for a project."
  (interactive)
  (let* ((project (if (= (length templedb-agent--projects) 1)
                      (car templedb-agent--projects)
                    (completing-read "Project: " templedb-agent--projects nil t)))
         (items (cdr (assoc project templedb-agent--context-config)))
         (choices (mapcar (lambda (pair)
                           (let* ((key (car pair))
                                  (label (cdr pair))
                                  (val (alist-get key items)))
                             (format "[%s] %s" (if val "X" " ") label)))
                         templedb-agent--context-items))
         (choice (completing-read "Toggle: " choices nil t))
         (idx (cl-position choice choices :test #'equal))
         (key (car (nth idx templedb-agent--context-items))))
    (let ((entry (assoc project templedb-agent--context-config)))
      (when entry
        (setf (alist-get key (cdr entry)) (not (alist-get key (cdr entry))))))
    (templedb-agent--render-context-section)
    (message "Toggled %s for %s" (cdr (nth idx templedb-agent--context-items)) project)))

(defun templedb-agent-list-context ()
  "Show current context projects."
  (interactive)
  (message "Context: %s"
           (mapconcat #'identity (or templedb-agent--projects '("(none)")) ", ")))

(defun templedb-agent-add-buffer ()
  "Add current buffer file to agent context."
  (interactive)
  (let ((file (buffer-file-name)))
    (if file
        (templedb-agent--insert-conversation-entry
         "templedb" (format "[Context] File: %s" file))
      (user-error "Buffer has no file"))))

(defun templedb-agent-add-region (start end)
  "Add selected region to agent context."
  (interactive "r")
  (let ((text (buffer-substring-no-properties start end))
        (file (or (buffer-file-name) (buffer-name))))
    (templedb-agent--insert-conversation-entry
     "templedb"
     (format "[Context] Selection from %s:\n#+begin_src\n%s\n#+end_src" file text))))

(defun templedb-agent-ask-about-point ()
  "Ask the agent about the thing at point."
  (interactive)
  (let* ((sym (thing-at-point 'symbol t))
         (file (or (buffer-file-name) (buffer-name)))
         (line (line-number-at-pos))
         (agent-buf (seq-find
                     (lambda (b) (with-current-buffer b
                                   (and (eq major-mode 'templedb-agent-mode)
                                        templedb-agent--session-id)))
                     (buffer-list))))
    (unless agent-buf (user-error "No active Temple Agent session"))
    (unless sym (user-error "No symbol at point"))
    (with-current-buffer agent-buf
      (templedb-agent--insert-conversation-entry
       "user" (format "What is `%s` at %s:%d?" sym file line))
      (templedb-agent--send
       "message.send"
       `((session_id . ,templedb-agent--session-id)
         (content . ,(format "What is `%s` at %s:%d?" sym file line)))
       (lambda (_result) nil)))
    (switch-to-buffer-other-window agent-buf)))

;;;; Major mode

(defvar templedb-agent-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c C-c") #'templedb-agent-send)
    (define-key map (kbd "C-c C-k") #'templedb-agent-cancel)
    (define-key map (kbd "C-c C-r") #'templedb-agent-resume)
    map)
  "Keymap for `templedb-agent-mode'.")

(define-derived-mode templedb-agent-mode org-mode "TAgent"
  "Major mode for Temple Agent sessions."
  (setq-local buffer-read-only nil)
  ;; Raise undo limit -- streaming creates large entries
  (setq-local undo-outer-limit 50000000)  ; 50MB
  ;; Enable word wrap so long lines are visible
  (visual-line-mode 1)
  (setq-local word-wrap t)
  (setq-local truncate-lines nil)
  (use-local-map (make-composed-keymap
                  templedb-agent-mode-map org-mode-map)))

;;;; Cleanup and debugging

(defun templedb-agent-close ()
  "Close the current agent session and kill the buffer."
  (interactive)
  (when templedb-agent--session-id
    (templedb-agent--send
     "session.close"
     `((session_id . ,templedb-agent--session-id))
     (lambda (_result) nil)))
  (when (and templedb-agent--process (process-live-p templedb-agent--process))
    (delete-process templedb-agent--process))
  (kill-buffer))

(defun templedb-agent-debug ()
  "Show debug info about the current agent session."
  (interactive)
  (let ((info (list
               (format "Session ID: %s" templedb-agent--session-id)
               (format "Status: %s" templedb-agent--status)
               (format "Provider: %s" templedb-agent--provider)
               (format "Projects: %s" templedb-agent--projects)
               (format "Process: %s"
                       (if (and templedb-agent--process
                                (process-live-p templedb-agent--process))
                           (format "alive (pid %s)"
                                   (process-id templedb-agent--process))
                         "dead"))
               (format "Pending requests: %d"
                       (length templedb-agent--pending-requests))
               (format "Streaming: %s"
                       (if templedb-agent--streaming-marker "yes" "no"))
               (format "Stderr: %s"
                       (if-let ((sb (get-buffer "*temple-agent-stderr*")))
                           (with-current-buffer sb
                             (let ((s (string-trim (buffer-string))))
                               (if (string-empty-p s) "(empty)"
                                 (car (last (split-string s "\n"))))))
                         "(no buffer)")))))
    (message "%s" (mapconcat #'identity info "\n"))
    (with-current-buffer (get-buffer-create "*Temple Agent Debug*")
      (let ((inhibit-read-only t))
        (erase-buffer)
        (dolist (line info) (insert line "\n"))
        (insert "\n--- Stderr ---\n")
        (when-let ((sb (get-buffer "*temple-agent-stderr*")))
          (insert (with-current-buffer sb (buffer-string)))))
      (special-mode)
      (display-buffer (current-buffer)))))

(defun templedb-agent-kill-process ()
  "Force-kill the agent process (unstick a frozen session)."
  (interactive)
  (when (and templedb-agent--process (process-live-p templedb-agent--process))
    (kill-process templedb-agent--process)
    (message "Agent process killed"))
  (setq templedb-agent--process nil)
  (templedb-agent--set-now "Process killed (use , r to resume or C-c C-c to send new message)")
  (templedb-agent--set-status "interrupted"))

;; Spacemacs keys are registered in packages.el (the proper Spacemacs way).

(provide 'templedb-agent)

;;; templedb-agent.el ends here
