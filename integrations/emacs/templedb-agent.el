;;; templedb-agent.el --- Temple Agent: native AI in Emacs -*- lexical-binding: t; -*-
;;
;; Author: Zach Abel
;; Package-Requires: ((emacs "28.1"))
;;
;;; Commentary:
;;
;; Temple Agent — Claude Code inside Emacs, but native.
;; Uses TempleDB for memory, Org for display, JSON-lines for protocol.
;;
;; Entry point: M-x templedb-agent-new or SPC , a n
;;
;; Architecture:
;;   Emacs buffer (Org) <-> JSON protocol <-> templedb ai agent serve <-> Provider
;;
;; Buffer keybindings:
;;   , RET   send prompt
;;   , i     guide Claude
;;   , c     cancel
;;   , r     resume
;;   , g     refresh
;;   C-c C-c send
;;   C-c C-k cancel
;;   C-c C-r resume

;;; Code:

(require 'json)
(require 'org)

;;;; ═══════════════════════════════════════════════════════════════
;;;; Configuration
;;;; ═══════════════════════════════════════════════════════════════

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

(defcustom templedb-agent-default-provider "fake"
  "Default AI provider for new sessions."
  :type '(choice (const "fake") (const "claude-code"))
  :group 'templedb-agent)

;;;; ═══════════════════════════════════════════════════════════════
;;;; State
;;;; ═══════════════════════════════════════════════════════════════

(defvar-local templedb-agent--session-id nil
  "Current session ID for this buffer.")

(defvar-local templedb-agent--run-id nil
  "Current run ID.")

(defvar-local templedb-agent--status "created"
  "Current session status.")

(defvar-local templedb-agent--project nil
  "Project slug for this session.")

(defvar-local templedb-agent--provider nil
  "Provider name for this session.")

(defvar-local templedb-agent--process nil
  "The agent serve process for this buffer.")

(defvar-local templedb-agent--request-id 0
  "Monotonic request ID counter.")

(defvar-local templedb-agent--pending-requests nil
  "Alist of (id . callback) for pending requests.")

(defvar-local templedb-agent--partial-line ""
  "Incomplete JSON line from process output.")

(defvar-local templedb-agent--streaming-text ""
  "Accumulated streaming text from assistant.")

(defvar-local templedb-agent--streaming-marker nil
  "Marker for where streaming text is being inserted.")

(defvar-local templedb-agent--now-text ""
  "Current 'Now' section text.")

;;;; ═══════════════════════════════════════════════════════════════
;;;; Process management
;;;; ═══════════════════════════════════════════════════════════════

(defun templedb-agent--start-process ()
  "Start the agent serve process."
  (when (and templedb-agent--process
             (process-live-p templedb-agent--process))
    (delete-process templedb-agent--process))
  (let ((process-environment (append '("PYTHONDONTWRITEBYTECODE=1") process-environment))
        (buf (current-buffer)))
    (setq templedb-agent--process
          (make-process
           :name (format "temple-agent-%s" (or templedb-agent--session-id "new"))
           :buffer (generate-new-buffer " *temple-agent-proc*")
           :command (list templedb-agent-executable "ai" "agent" "serve" "--stdio")
           :connection-type 'pipe
           :noquery t
           :filter (lambda (proc output)
                     (templedb-agent--process-filter buf proc output))
           :sentinel (lambda (proc event)
                       (templedb-agent--process-sentinel buf proc event)))))
  templedb-agent--process)

(defun templedb-agent--process-filter (agent-buf _proc output)
  "Handle output from the agent process, parsing JSON lines."
  (when (buffer-live-p agent-buf)
    (with-current-buffer agent-buf
      ;; Accumulate partial lines
      (setq templedb-agent--partial-line
            (concat templedb-agent--partial-line output))
      ;; Process complete lines
      (let ((lines (split-string templedb-agent--partial-line "\n")))
        ;; Last element is incomplete (or empty if output ends with \n)
        (setq templedb-agent--partial-line (car (last lines)))
        ;; Process all complete lines
        (dolist (line (butlast lines))
          (let ((trimmed (string-trim line)))
            (when (and (not (string-empty-p trimmed))
                       ;; Skip log lines (INFO, WARNING, etc.)
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
        (templedb-agent--set-now "Process ended")
        (templedb-agent--set-status "interrupted")))))

(defun templedb-agent--send (method params &optional callback)
  "Send a JSON-lines request to the agent process.
If CALLBACK is non-nil, call it with the result when response arrives."
  (unless (and templedb-agent--process
               (process-live-p templedb-agent--process))
    (templedb-agent--start-process))
  (cl-incf templedb-agent--request-id)
  (let ((id templedb-agent--request-id)
        (request `((id . ,templedb-agent--request-id)
                   (method . ,method)
                   (params . ,params))))
    (when callback
      (push (cons id callback) templedb-agent--pending-requests))
    (let ((json-str (concat (json-encode request) "\n")))
      (process-send-string templedb-agent--process json-str))
    id))

;;;; ═══════════════════════════════════════════════════════════════
;;;; Message handling
;;;; ═══════════════════════════════════════════════════════════════

(defun templedb-agent--handle-message (msg)
  "Handle a parsed JSON message from the agent process."
  (let ((id (alist-get 'id msg))
        (method (alist-get 'method msg))
        (result (alist-get 'result msg))
        (error-msg (alist-get 'error msg)))
    (cond
     ;; Response to a request
     (id
      (let ((callback (alist-get id templedb-agent--pending-requests)))
        (setq templedb-agent--pending-requests
              (assq-delete-all id templedb-agent--pending-requests))
        (when callback
          (if error-msg
              (message "Temple Agent error: %s" error-msg)
            (funcall callback result)))))
     ;; Event push
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
       (let ((text (alist-get 'text data)))
         (when text
           (templedb-agent--append-streaming text))))

      ("assistant.completed"
       (templedb-agent--set-now "Response complete"))

      ("tool.started"
       (templedb-agent--set-now (or summary "Running tool..."))
       (templedb-agent--insert-tool-heading summary "RUNNING"))

      ("tool.completed"
       (templedb-agent--update-tool-heading summary "DONE"))

      ("tool.failed"
       (templedb-agent--update-tool-heading summary "FAILED"))

      ("provider.rate_limited"
       (templedb-agent--set-now "Rate limited. Waiting..."))

      ("provider.login_required"
       (templedb-agent--set-now "Login required. Run: claude auth login"))

      ("service.recovered"
       (message "Temple Agent: %s" (or summary "Sessions recovered"))))))

;;;; ═══════════════════════════════════════════════════════════════
;;;; Org buffer rendering
;;;; ═══════════════════════════════════════════════════════════════

(defun templedb-agent--render-buffer ()
  "Render the full agent Org buffer."
  (let ((inhibit-read-only t))
    (erase-buffer)
    (insert (format "#+TITLE: Temple Agent\n"))
    (insert (format "#+TDB_SESSION_ID: %s\n" (or templedb-agent--session-id "")))
    (insert (format "#+TDB_PROJECT: %s\n" (or templedb-agent--project "")))
    (insert (format "#+TDB_STATUS: %s\n\n" templedb-agent--status))

    ;; Now section
    (insert "* Now\n\n")
    (insert (or templedb-agent--now-text "Ready") "\n\n")

    ;; Goal section (editable)
    (insert "* Goal\n\n\n")

    ;; Context section
    (insert "* Context\n\n")
    (when templedb-agent--project
      (insert (format "- Current project: %s\n" templedb-agent--project)))
    (insert "\n")

    ;; Conversation section
    (insert "* Conversation\n\n")

    ;; Next Prompt section (editable)
    (insert "* Next Prompt\n\n")
    (insert "Type next message here.\n\n")

    ;; Notes section (editable)
    (insert "* Notes\n\n\n")

    ;; Scratch section (editable)
    (insert "* Scratch\n\n\n")))

(defun templedb-agent--set-now (text)
  "Update the Now section."
  (setq templedb-agent--now-text text)
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* Now\n\n" nil t)
      (let ((start (point))
            (end (if (re-search-forward "^\\* " nil t)
                     (match-beginning 0)
                   (point-max))))
        (let ((inhibit-read-only t))
          (delete-region start end)
          (goto-char start)
          (insert text "\n\n"))))))

(defun templedb-agent--set-status (status)
  "Update the session status in header and variable."
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
            (insert (format "\n** %s\n\n%s\n"
                            (capitalize role) text))))
      ;; Fallback: insert at end of Conversation section
      (goto-char (point-min))
      (when (re-search-forward "^\\* Conversation\n" nil t)
        (goto-char (if (re-search-forward "^\\* " nil t)
                       (match-beginning 0)
                     (point-max)))
        (let ((inhibit-read-only t))
          (insert (format "\n** %s\n\n%s\n"
                          (capitalize role) text)))))))

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
      ;; Fallback
      (goto-char (point-max))
      (let ((inhibit-read-only t))
        (insert "\n** Assistant\n\n")
        (setq templedb-agent--streaming-marker (point-marker))))))

(defun templedb-agent--append-streaming (text)
  "Append TEXT to the streaming assistant response."
  (setq templedb-agent--streaming-text
        (concat templedb-agent--streaming-text text))
  (when (and templedb-agent--streaming-marker
             (marker-buffer templedb-agent--streaming-marker))
    (save-excursion
      (goto-char templedb-agent--streaming-marker)
      (let ((inhibit-read-only t))
        (insert text)
        (set-marker templedb-agent--streaming-marker (point))))))

(defun templedb-agent--finalize-streaming ()
  "Finalize the streaming response."
  (when templedb-agent--streaming-marker
    (save-excursion
      (goto-char templedb-agent--streaming-marker)
      (let ((inhibit-read-only t))
        (insert "\n")))
    (set-marker templedb-agent--streaming-marker nil)
    (setq templedb-agent--streaming-marker nil))
  (setq templedb-agent--streaming-text ""))

(defun templedb-agent--insert-tool-heading (summary status)
  "Insert a tool activity heading."
  (save-excursion
    (goto-char (point-min))
    (if (re-search-forward "^\\* Next Prompt" nil t)
        (progn
          (forward-line -1)
          (let ((inhibit-read-only t))
            (insert (format "\n** %s %s\n" status (or summary "tool")))))
      (goto-char (point-max))
      (let ((inhibit-read-only t))
        (insert (format "\n** %s %s\n" status (or summary "tool")))))))

(defun templedb-agent--update-tool-heading (summary new-status)
  "Update the latest tool heading matching SUMMARY to NEW-STATUS."
  (save-excursion
    (goto-char (point-max))
    (when (re-search-backward
           (format "^\\*\\* \\(RUNNING\\|DONE\\|FAILED\\) %s$"
                   (regexp-quote (or summary "")))
           nil t)
      (let ((inhibit-read-only t))
        (replace-match (format "** %s %s" new-status (or summary "")) t t)))))

(defun templedb-agent--restore-messages (messages)
  "Restore conversation from saved MESSAGES."
  (dolist (msg messages)
    (let ((role (alist-get 'role msg))
          (text (alist-get 'content_text msg)))
      (when (and role text (not (string-empty-p text)))
        (templedb-agent--insert-conversation-entry role text)))))

;;;; ═══════════════════════════════════════════════════════════════
;;;; User commands
;;;; ═══════════════════════════════════════════════════════════════

(defun templedb-agent--get-prompt-text ()
  "Get the text from the Next Prompt section."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* Next Prompt\n\n" nil t)
      (let ((start (point))
            (end (if (re-search-forward "^\\* " nil t)
                     (match-beginning 0)
                   (point-max))))
        (string-trim (buffer-substring-no-properties start end))))))

(defun templedb-agent--clear-prompt ()
  "Clear the Next Prompt section."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\* Next Prompt\n\n" nil t)
      (let ((start (point))
            (end (if (re-search-forward "^\\* " nil t)
                     (match-beginning 0)
                   (point-max))))
        (let ((inhibit-read-only t))
          (delete-region start end)
          (goto-char start)
          (insert "\n"))))))

(defun templedb-agent-send ()
  "Send the message in Next Prompt to the agent.
If a run is active, queue the message instead."
  (interactive)
  (let ((text (templedb-agent--get-prompt-text)))
    (when (or (null text) (string-empty-p text))
      (user-error "No message to send. Type in the Next Prompt section"))
    ;; Show user message in conversation
    (templedb-agent--insert-conversation-entry "user" text)
    (templedb-agent--clear-prompt)
    ;; Queue if running, send otherwise
    (if (equal templedb-agent--status "running")
        (progn
          (templedb-agent--send
           "message.queue"
           `((session_id . ,templedb-agent--session-id)
             (content . ,text))
           (lambda (_result) (message "Message queued (Claude is working)"))))
      (templedb-agent--send
       "message.send"
       `((session_id . ,templedb-agent--session-id)
         (content . ,text))
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
  "Refresh the buffer from database state.
Uses server-rendered Org for full fidelity recovery."
  (interactive)
  (templedb-agent--send
   "session.open"
   `((session_id . ,templedb-agent--session-id))
   (lambda (result)
     (let ((session (alist-get 'session result))
           (org-text (alist-get 'org result)))
       (setq templedb-agent--status (alist-get 'status session))
       (setq templedb-agent--project
             (or (alist-get 'project_slug session)
                 templedb-agent--project))
       (setq templedb-agent--provider
             (or (alist-get 'provider_name session)
                 templedb-agent--provider))
       ;; Replace buffer with server-rendered Org
       (when org-text
         (let ((inhibit-read-only t)
               (pos (point)))
           (erase-buffer)
           (insert org-text)
           (goto-char (min pos (point-max)))))))))

;;;; ═══════════════════════════════════════════════════════════════
;;;; Session management
;;;; ═══════════════════════════════════════════════════════════════

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
    (setq templedb-agent--provider templedb-agent-default-provider)
    ;; Start process and create session
    (templedb-agent--start-process)
    ;; Give process a moment to start
    (run-at-time 0.3 nil
                 (lambda ()
                   (when (buffer-live-p buf)
                     (with-current-buffer buf
                       (templedb-agent--send
                        "session.create"
                        `((provider . ,templedb-agent--provider)
                          (project . ,templedb-agent--project))
                        (lambda (result)
                          (setq templedb-agent--session-id (alist-get 'id result))
                          (templedb-agent--render-buffer)
                          (templedb-agent--set-now "Ready")
                          (message "Temple Agent session %d created"
                                   templedb-agent--session-id)))))))))

;;;###autoload
(defun templedb-agent-open (session-id)
  "Open an existing Temple Agent session by SESSION-ID."
  (interactive "nSession ID: ")
  (let* ((buf-name (format "*Temple Agent: #%d*" session-id))
         (buf (get-buffer-create buf-name)))
    (switch-to-buffer buf)
    (templedb-agent-mode)
    (setq templedb-agent--session-id session-id)
    (templedb-agent--start-process)
    (run-at-time 0.3 nil
                 (lambda ()
                   (when (buffer-live-p buf)
                     (with-current-buffer buf
                       (templedb-agent--send
                        "session.open"
                        `((session_id . ,session-id))
                        (lambda (result)
                          (let ((session (alist-get 'session result))
                                (org-text (alist-get 'org result)))
                            (setq templedb-agent--project
                                  (or (alist-get 'project_slug session) ""))
                            (setq templedb-agent--provider
                                  (alist-get 'provider_name session))
                            (setq templedb-agent--status
                                  (alist-get 'status session))
                            ;; Use server-rendered Org for full recovery
                            (if org-text
                                (let ((inhibit-read-only t))
                                  (erase-buffer)
                                  (insert org-text))
                              ;; Fallback: render locally
                              (templedb-agent--render-buffer))
                            (message "Temple Agent session %d opened (%s)"
                                     session-id
                                     (alist-get 'status session)))))))))))

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
  (let ((output (with-temp-buffer
                  (call-process templedb-agent-executable nil t nil
                                "ai" "agent" "doctor"
                                "--provider" templedb-agent-default-provider)
                  (buffer-string))))
    (message "%s" (string-trim output))))

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
     (let ((new-id (alist-get 'id result)))
       (templedb-agent-open new-id)
       (message "Forked session %d -> %d"
                templedb-agent--session-id new-id)))))

;;;###autoload
(defun templedb-agent-switch ()
  "Switch to a different agent session."
  (interactive)
  ;; Get list of sessions via CLI
  (let* ((output (with-temp-buffer
                   (call-process templedb-agent-executable nil t nil
                                 "ai" "agent" "sessions" "--json")
                   (buffer-string)))
         (sessions (condition-case nil
                       (json-read-from-string output)
                     (error nil))))
    (if (or (null sessions) (= (length sessions) 0))
        (message "No sessions to switch to")
      (let* ((choices (mapcar
                       (lambda (s)
                         (format "%d: %s [%s]"
                                 (alist-get 'id s)
                                 (or (alist-get 'title s) "(untitled)")
                                 (alist-get 'status s)))
                       (append sessions nil)))
             (choice (completing-read "Session: " choices nil t))
             (id (string-to-number choice)))
        (templedb-agent-open id)))))

;;;; ═══════════════════════════════════════════════════════════════
;;;; Context basket
;;;; ═══════════════════════════════════════════════════════════════

(defun templedb-agent-add-buffer ()
  "Add current buffer's file to agent context."
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
    (unless agent-buf
      (user-error "No active Temple Agent session"))
    (unless sym
      (user-error "No symbol at point"))
    (with-current-buffer agent-buf
      (templedb-agent--insert-conversation-entry
       "user" (format "What is `%s` at %s:%d?" sym file line))
      (templedb-agent--send
       "message.send"
       `((session_id . ,templedb-agent--session-id)
         (content . ,(format "What is `%s` at %s:%d?" sym file line)))
       (lambda (_result) nil)))
    (switch-to-buffer-other-window agent-buf)))

;;;; ═══════════════════════════════════════════════════════════════
;;;; Major mode
;;;; ═══════════════════════════════════════════════════════════════

(defvar templedb-agent-mode-map
  (let ((map (make-sparse-keymap)))
    ;; Standard Emacs keys
    (define-key map (kbd "C-c C-c") #'templedb-agent-send)
    (define-key map (kbd "C-c C-k") #'templedb-agent-cancel)
    (define-key map (kbd "C-c C-r") #'templedb-agent-resume)
    map)
  "Keymap for `templedb-agent-mode'.")

(define-derived-mode templedb-agent-mode org-mode "TAgent"
  "Major mode for Temple Agent sessions.
\\{templedb-agent-mode-map}"
  (setq-local buffer-read-only nil)
  ;; Keep org functionality but add our keys
  (use-local-map (make-composed-keymap
                  templedb-agent-mode-map
                  org-mode-map)))

;;;; ═══════════════════════════════════════════════════════════════
;;;; Spacemacs integration
;;;; ═══════════════════════════════════════════════════════════════

(defun templedb-agent--setup-spacemacs-keys ()
  "Set up Spacemacs leader keys for Temple Agent."
  (when (fboundp 'spacemacs/declare-prefix)
    ;; Global keys under SPC a T A (agent sub-prefix)
    (spacemacs/declare-prefix "aTA" "agent")
    (spacemacs/set-leader-keys
      "aTAn" 'templedb-agent-new
      "aTAo" 'templedb-agent-open
      "aTAl" 'templedb-agent-list
      "aTAr" 'templedb-agent-resume
      "aTAd" 'templedb-agent-doctor
      "aTA?" 'templedb-agent-ask-about-point)

    ;; Buffer-local keys for agent mode
    (spacemacs/set-leader-keys-for-major-mode 'templedb-agent-mode
      ;; Core
      "RET" 'templedb-agent-send
      "i"   'templedb-agent-guide
      "c"   'templedb-agent-cancel
      "r"   'templedb-agent-resume
      "g"   'templedb-agent-refresh
      ;; Context
      "xb"  'templedb-agent-add-buffer
      "xv"  'templedb-agent-add-region
      ;; Sessions
      "sn"  'templedb-agent-new
      "ss"  'templedb-agent-switch
      "sl"  'templedb-agent-list
      "sf"  'templedb-agent-fork
      "sq"  'templedb-agent-close)))

(defun templedb-agent-close ()
  "Close the current agent session and kill the buffer."
  (interactive)
  (when templedb-agent--session-id
    (templedb-agent--send
     "session.close"
     `((session_id . ,templedb-agent--session-id))
     (lambda (_result) nil)))
  (when (and templedb-agent--process
             (process-live-p templedb-agent--process))
    (delete-process templedb-agent--process))
  (kill-buffer))

;; Auto-setup Spacemacs keys when loaded
(with-eval-after-load 'spacemacs-bootstrap
  (templedb-agent--setup-spacemacs-keys))

;; Also try at load time (for non-lazy loading)
(when (fboundp 'spacemacs/set-leader-keys)
  (templedb-agent--setup-spacemacs-keys))

(provide 'templedb-agent)

;;; templedb-agent.el ends here
