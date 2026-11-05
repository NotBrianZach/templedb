;;; test-templedb-agent.el --- ERT tests for templedb-agent.el  -*- lexical-binding: t; -*-
;;
;; Run with:
;;   emacs --batch -Q -L integrations/emacs \
;;         -l integrations/emacs/templedb-agent.el \
;;         -l integrations/emacs/test-templedb-agent.el \
;;         -f ert-run-tests-batch-and-exit
;;
;; What's covered:
;;   * Section anchors: --find-section, --next-section-after, --section-end
;;   * Ewoc lifecycle: --enter-exchange, --mutate-last-exchange, invalidation
;;   * Streaming: --append-assistant-delta accumulates and re-renders
;;   * Tools: --add-tool creates bucket, --update-tool mutates in place
;;   * Restore: --restore-conversation builds N exchanges from DB shape
;;   * Persistence firewall: run.completed does NOT persist user sections
;;   * The historical bug: no `*** Other' ever lands past `end-of-conversation'
;;     regardless of event pattern or race
;;
;; These tests all run in a headless `with-temp-buffer' with
;; `templedb-agent-mode' active, so they don't touch DB or process.

;;; Code:

(require 'ert)
(require 'ewoc)
(require 'cl-lib)

;; templedb-agent.el is expected to be loaded before this file.

(defmacro templedb-agent-test--in-buffer (&rest body)
  "Set up a fresh agent buffer, render it, then run BODY inside it."
  (declare (indent 0) (debug (body)))
  `(with-temp-buffer
     (templedb-agent-mode)
     (templedb-agent--render-buffer)
     ,@body))

(defun templedb-agent-test--buffer-of-conversation ()
  "Return the buffer substring between the Conversation and Next Prompt anchors."
  (buffer-substring-no-properties
   (templedb-agent--find-section 'conversation)
   (templedb-agent--find-section 'next-prompt)))

(defun templedb-agent-test--other-buckets-past-eoc ()
  "Return positions of any `*** Other' heading past end-of-conversation."
  (save-excursion
    (goto-char (templedb-agent--end-of-conversation))
    (let (positions)
      (while (re-search-forward "^\\*\\*\\* Other$" nil t)
        (push (match-beginning 0) positions))
      (nreverse positions))))


;;;; Section anchors ------------------------------------------------------

(ert-deftest templedb-agent-test/anchors-are-set-on-all-sections ()
  (templedb-agent-test--in-buffer
    (dolist (id templedb-agent--section-order)
      (should (integerp (templedb-agent--find-section id))))))

(ert-deftest templedb-agent-test/anchors-are-ordered ()
  (templedb-agent-test--in-buffer
    (let ((positions (mapcar #'templedb-agent--find-section
                             templedb-agent--section-order)))
      (should (equal positions (sort (copy-sequence positions) #'<))))))

(ert-deftest templedb-agent-test/end-of-conversation-equals-next-prompt-anchor ()
  (templedb-agent-test--in-buffer
    (should (= (templedb-agent--end-of-conversation)
               (templedb-agent--find-section 'next-prompt)))))

(ert-deftest templedb-agent-test/anchors-survive-user-typed-headings-in-conversation ()
  "Regression: typing a `* Next Prompt' line inside Conversation used to
break the regex-based end-of-conversation and pull inserts to the wrong
region. With anchors, this is impossible."
  (templedb-agent-test--in-buffer
    (goto-char (templedb-agent--find-section 'conversation))
    (forward-line 1)
    (let ((inhibit-read-only t))
      (insert "* Next Prompt\n"))
    ;; The REAL Next Prompt anchor should still be found and used.
    (let ((real-np (templedb-agent--find-section 'next-prompt)))
      (should (integerp real-np))
      (should (= (templedb-agent--end-of-conversation) real-np))
      (should (> real-np (point))))))

(ert-deftest templedb-agent-test/next-section-after-walks-anchor-chain ()
  (templedb-agent-test--in-buffer
    (let ((notes (templedb-agent--find-section 'notes))
          (scratch (templedb-agent--find-section 'scratch)))
      (should (= scratch (templedb-agent--next-section-after notes))))))


;;;; Ewoc lifecycle -------------------------------------------------------

(ert-deftest templedb-agent-test/ewoc-is-created-and-empty ()
  (templedb-agent-test--in-buffer
    (should templedb-agent--conv-ewoc)
    (should-not (ewoc-nth templedb-agent--conv-ewoc 0))))

(ert-deftest templedb-agent-test/enter-exchange-adds-node ()
  (templedb-agent-test--in-buffer
    (templedb-agent--enter-exchange "hello")
    (should (ewoc-nth templedb-agent--conv-ewoc 0))
    (should (equal "hello" (plist-get (ewoc-data (ewoc-nth templedb-agent--conv-ewoc 0))
                                      :user-text)))))

(ert-deftest templedb-agent-test/exchange-renders-user-heading ()
  (templedb-agent-test--in-buffer
    (templedb-agent--enter-exchange "hello world")
    (should (string-match-p "\\*\\* hello world"
                            (templedb-agent-test--buffer-of-conversation)))
    (should (string-match-p "\\*\\*\\* User"
                            (templedb-agent-test--buffer-of-conversation)))))


;;;; Streaming ------------------------------------------------------------

(ert-deftest templedb-agent-test/assistant-delta-accumulates ()
  (templedb-agent-test--in-buffer
    (templedb-agent--enter-exchange "q")
    (templedb-agent--append-assistant-delta "Hello ")
    (templedb-agent--append-assistant-delta "world!")
    (let ((ex (ewoc-data (ewoc-nth templedb-agent--conv-ewoc 0))))
      (should (equal "Hello world!" (plist-get ex :assistant-text))))
    (should (string-match-p "Hello world!"
                            (templedb-agent-test--buffer-of-conversation)))))

(ert-deftest templedb-agent-test/mark-assistant-done-flags-node ()
  (templedb-agent-test--in-buffer
    (templedb-agent--enter-exchange "q")
    (templedb-agent--append-assistant-delta "a")
    (templedb-agent--mark-assistant-done)
    (should (plist-get (ewoc-data (ewoc-nth templedb-agent--conv-ewoc 0))
                       :assistant-done))))


;;;; Tools ----------------------------------------------------------------

(ert-deftest templedb-agent-test/add-tool-creates-bucket ()
  (templedb-agent-test--in-buffer
    (templedb-agent--enter-exchange "q")
    (templedb-agent--add-tool
     "Other"
     '(:id "t1" :name "Bash" :input "ls" :bucket "Other"
       :status running :summary "Bash(ls)" :output nil :duration nil))
    (let ((ex (ewoc-data (ewoc-nth templedb-agent--conv-ewoc 0))))
      (should (equal 1 (length (cdr (assoc "Other" (plist-get ex :buckets)))))))
    (should (string-match-p "\\*\\*\\* Other"
                            (templedb-agent-test--buffer-of-conversation)))
    (should (string-match-p "\\*\\*\\*\\* RUNNING Bash(ls)"
                            (templedb-agent-test--buffer-of-conversation)))))

(ert-deftest templedb-agent-test/update-tool-mutates-status-and-output ()
  (templedb-agent-test--in-buffer
    (templedb-agent--enter-exchange "q")
    (templedb-agent--add-tool
     "Other"
     '(:id "t1" :name "Bash" :input "ls" :bucket "Other"
       :status running :summary "Bash(ls)" :output nil :duration nil))
    (templedb-agent--update-tool "t1"
      (lambda (tool)
        (plist-put tool :status 'done)
        (plist-put tool :output "file1\nfile2")
        (plist-put tool :duration 1.5)))
    (let* ((ex (ewoc-data (ewoc-nth templedb-agent--conv-ewoc 0)))
           (tool (car (cdr (assoc "Other" (plist-get ex :buckets))))))
      (should (eq 'done (plist-get tool :status)))
      (should (equal "file1\nfile2" (plist-get tool :output))))
    (should (string-match-p "\\*\\*\\*\\* DONE Bash(ls)"
                            (templedb-agent-test--buffer-of-conversation)))
    (should (string-match-p "file1"
                            (templedb-agent-test--buffer-of-conversation)))))


;;;; The historical bug ---------------------------------------------------

(ert-deftest templedb-agent-test/no-tool-ever-lands-past-end-of-conversation ()
  "Regression: prior to the ewoc rewrite, some code path let `*** Other'
buckets be created past `* Next Prompt', ending up inside `* Scratch'.
This test simulates the run 46 pattern (multiple tool.started, no
tool.completed, no user_target) and asserts nothing leaks."
  (templedb-agent-test--in-buffer
    (templedb-agent--enter-exchange "deploy this")
    (dolist (id '("t1" "t2" "t3"))
      (templedb-agent--add-tool
       "Other"
       (list :id id :name "Bash" :input "cmd" :bucket "Other"
             :status 'running :summary (format "Bash(%s)" id)
             :output nil :duration nil)))
    (should (equal nil (templedb-agent-test--other-buckets-past-eoc)))))

(ert-deftest templedb-agent-test/scratch-stays-clean-across-many-events ()
  (templedb-agent-test--in-buffer
    (templedb-agent--enter-exchange "big turn")
    (dotimes (i 20)
      (templedb-agent--add-tool
       "Other"
       (list :id (format "t%d" i) :name "Bash" :input "cmd" :bucket "Other"
             :status 'running :summary "Bash(x)"
             :output nil :duration nil))
      (templedb-agent--append-assistant-delta (format "chunk-%d " i)))
    (let ((scratch-start (templedb-agent--find-section 'scratch)))
      (should (string-match-p
               "\\`\\* Scratch\n\n?\n?\\'"
               (buffer-substring-no-properties scratch-start (point-max)))))))


;;;; Restore --------------------------------------------------------------

(ert-deftest templedb-agent-test/restore-builds-n-exchanges ()
  (templedb-agent-test--in-buffer
    (templedb-agent--restore-conversation
     '(((role . "user") (content_text . "one") (run_id . 1))
       ((role . "assistant") (content_text . "1a") (run_id . 1))
       ((role . "user") (content_text . "two") (run_id . 2))
       ((role . "assistant") (content_text . "2a") (run_id . 2)))
     nil)
    (let ((n (cl-loop for node = (ewoc-nth templedb-agent--conv-ewoc 0)
                      then (ewoc-next templedb-agent--conv-ewoc node)
                      while node count 1)))
      (should (= n 2)))))

(ert-deftest templedb-agent-test/restore-marks-assistants-done ()
  (templedb-agent-test--in-buffer
    (templedb-agent--restore-conversation
     '(((role . "user") (content_text . "q") (run_id . 1))
       ((role . "assistant") (content_text . "a") (run_id . 1)))
     nil)
    (let ((ex (ewoc-data (ewoc-nth templedb-agent--conv-ewoc 0))))
      (should (plist-get ex :assistant-done))
      (should (equal "a" (plist-get ex :assistant-text))))))


;;;; Persistence firewall -------------------------------------------------

(ert-deftest templedb-agent-test/run-completed-does-not-save ()
  "Regression: run.completed used to auto-persist user sections, which
could bake in polluted Scratch content. Now it MUST NOT."
  (templedb-agent-test--in-buffer
    (setq templedb-agent--session-id 999)
    (let ((sent nil))
      (cl-letf (((symbol-function 'templedb-agent--send)
                 (lambda (method &rest _) (push method sent))))
        (templedb-agent--handle-event
         '((type . "run.completed") (summary . "Done") (data . ())))
        ;; No 'notes.set' should be in `sent'.
        (should-not (member "notes.set" sent))))))

(ert-deftest templedb-agent-test/scratch-polluted-p-recognises-tool-markers ()
  (should (templedb-agent--scratch-is-polluted-p ":TOOL_ID: xxx"))
  (should (templedb-agent--scratch-is-polluted-p "**** RUNNING foo"))
  (should (templedb-agent--scratch-is-polluted-p "**** DONE bar"))
  (should-not (templedb-agent--scratch-is-polluted-p "just user notes"))
  (should-not (templedb-agent--scratch-is-polluted-p "")))


;;;; Agent-writable sections (Phase D) ------------------------------------

(ert-deftest templedb-agent-test/section-anchors-cover-agent-sections ()
  (templedb-agent-test--in-buffer
    (dolist (id '(findings todo open-questions))
      (should (integerp (templedb-agent--find-section id))))))

(ert-deftest templedb-agent-test/finding-add-and-remove ()
  (templedb-agent-test--in-buffer
    (templedb-agent--handle-event
     '((type . "agent.section.finding.add")
       (data . ((id . "f1") (text . "webpack has custom mdx loader")))))
    (should (equal 1 (length templedb-agent--findings)))
    (let ((body (buffer-substring-no-properties
                 (templedb-agent--find-section 'findings)
                 (templedb-agent--section-end 'findings))))
      (should (string-match-p "webpack has custom mdx loader" body)))
    (templedb-agent--handle-event
     '((type . "agent.section.finding.remove")
       (data . ((id . "f1")))))
    (should (equal 0 (length templedb-agent--findings)))))

(ert-deftest templedb-agent-test/todo-add-done-remove ()
  (templedb-agent-test--in-buffer
    (templedb-agent--handle-event
     '((type . "agent.section.todo.add")
       (data . ((id . "t1") (text . "hook up MCP tool") (priority . "high")))))
    (should (eq 'high (plist-get (car templedb-agent--todos) :priority)))
    (templedb-agent--handle-event
     '((type . "agent.section.todo.done")
       (data . ((id . "t1")))))
    (should (plist-get (car templedb-agent--todos) :done))
    (let ((body (buffer-substring-no-properties
                 (templedb-agent--find-section 'todo)
                 (templedb-agent--section-end 'todo))))
      (should (string-match-p "\\[X\\] hook up MCP tool" body)))))

(ert-deftest templedb-agent-test/question-add-and-answer ()
  (templedb-agent-test--in-buffer
    (templedb-agent--handle-event
     '((type . "agent.section.question.add")
       (data . ((id . "q1") (text . "does prod use SameSite=None?")))))
    (templedb-agent--handle-event
     '((type . "agent.section.question.answered")
       (data . ((id . "q1") (answer . "yes, staging too")))))
    (let ((q (car templedb-agent--open-questions)))
      (should (plist-get q :answered))
      (should (equal "yes, staging too" (plist-get q :answer))))
    (let ((body (buffer-substring-no-properties
                 (templedb-agent--find-section 'open-questions)
                 (templedb-agent--section-end 'open-questions))))
      (should (string-match-p "yes, staging too" body)))))

(ert-deftest templedb-agent-test/dynamic-section-created-and-populated ()
  (templedb-agent-test--in-buffer
    (templedb-agent--handle-event
     '((type . "agent.section.dynamic.write")
       (data . ((section . "Blockers")
                (id . "b1")
                (text . "waiting on OAuth review")))))
    (let ((id (templedb-agent--dynamic-section-id "Blockers")))
      (should (integerp (templedb-agent--find-section id)))
      (should (member id templedb-agent--dynamic-section-order)))
    (let ((entries (cdr (assoc "Blockers" templedb-agent--dynamic-sections))))
      (should (equal 1 (length entries)))
      (should (equal "waiting on OAuth review"
                     (plist-get (car entries) :text))))))

(ert-deftest templedb-agent-test/dynamic-section-append-adds-multiple ()
  (templedb-agent-test--in-buffer
    (dolist (i '(1 2 3))
      (templedb-agent--handle-event
       `((type . "agent.section.dynamic.write")
         (data . ((section . "Discoveries")
                  (id . ,(format "d%d" i))
                  (text . ,(format "item %d" i)))))))
    (should (equal 3 (length (cdr (assoc "Discoveries"
                                         templedb-agent--dynamic-sections)))))))

(ert-deftest templedb-agent-test/dynamic-section-replace-mode ()
  (templedb-agent-test--in-buffer
    (templedb-agent--handle-event
     '((type . "agent.section.dynamic.write")
       (data . ((section . "Snapshot")
                (id . "s1") (text . "first")))))
    (templedb-agent--handle-event
     '((type . "agent.section.dynamic.write")
       (data . ((section . "Snapshot")
                (id . "s2") (text . "second")
                (mode . "replace")))))
    (let ((entries (cdr (assoc "Snapshot" templedb-agent--dynamic-sections))))
      (should (equal 1 (length entries)))
      (should (equal "second" (plist-get (car entries) :text))))))

(ert-deftest templedb-agent-test/agent-sections-do-not-touch-conversation ()
  "Regression: no matter how many agent-section events fire, the
Conversation region stays anchored between `conversation' and
`next-prompt', and no tool-bucket text ever leaks into any of the
new sections."
  (templedb-agent-test--in-buffer
    (templedb-agent--enter-exchange "user work")
    (templedb-agent--add-tool
     "Other"
     '(:id "t1" :name "Bash" :input "cmd" :bucket "Other"
       :status running :summary "Bash(x)" :output nil :duration nil))
    ;; Now spray a bunch of agent-section events
    (dotimes (i 5)
      (templedb-agent--handle-event
       `((type . "agent.section.finding.add")
         (data . ((id . ,(format "f%d" i)) (text . ,(format "note %d" i))))))
      (templedb-agent--handle-event
       `((type . "agent.section.todo.add")
         (data . ((id . ,(format "t%d" i)) (text . ,(format "task %d" i))))))
      (templedb-agent--handle-event
       `((type . "agent.section.dynamic.write")
         (data . ((section . "Random") (id . ,(format "r%d" i))
                  (text . ,(format "item %d" i))))))))
  ;; Tool bucket must still be inside Conversation.
  (should (equal nil (templedb-agent-test--other-buckets-past-eoc))))


(ert-deftest templedb-agent-test/reload-from-checkout-defined-and-bound ()
  "Phase 0 escape hatch: the reload command must exist and be bound to
C-c C-l in the agent mode map."
  (should (fboundp 'templedb-agent-reload-from-checkout))
  (should (commandp 'templedb-agent-reload-from-checkout))
  (should (eq (lookup-key templedb-agent-mode-map (kbd "C-c C-l"))
              'templedb-agent-reload-from-checkout))
  ;; Sanity: default checkout path is a string ending in the expected file.
  (should (stringp templedb-agent-checkout-path))
  (should (string-suffix-p "templedb-agent.el"
                           templedb-agent-checkout-path)))

(ert-deftest templedb-agent-test/reload-from-checkout-missing-file-warns ()
  "If the checkout doesn't exist, reload must print a warning and NOT
signal an error. Dev-mode should never crash Emacs."
  (let ((templedb-agent-checkout-path "/nonexistent/definitely-not-there.el")
        (msg nil))
    (cl-letf (((symbol-function 'message)
               (lambda (&rest args) (setq msg (apply #'format args)))))
      (templedb-agent-reload-from-checkout))
    (should msg)
    (should (string-match-p "checkout not found" msg))))


;;;; Filesystem alerts
;;
;; These drive the parse/deliver path over a temp directory with
;; `templedb-agent-alert-method' forced to nil, so nothing reaches a
;; notification daemon and the suite stays headless.

(defmacro templedb-agent-test--with-alert-dir (&rest body)
  "Run BODY with a fresh empty alert dir and clean watcher state."
  (declare (indent 0) (debug (body)))
  `(let* ((dir (make-temp-file "templedb-alerts-test-" t))
          (templedb-agent-alert-dir dir)
          (templedb-agent-alert-method nil)
          (templedb-agent-alert-kinds '("done" "failed" "ask" "login"))
          (templedb-agent--alert-seen (make-hash-table :test 'equal))
          (templedb-agent--alert-log nil))
     (unwind-protect (progn ,@body)
       (delete-directory dir t))))

(defun templedb-agent-test--drop-alert (name payload)
  "Write PAYLOAD (an alist) as alert file NAME in the current alert dir."
  (let ((path (expand-file-name name templedb-agent-alert-dir)))
    (with-temp-file path
      (insert (json-encode payload)))
    path))

(ert-deftest templedb-agent-test/alert-scan-delivers-new-files-once ()
  (templedb-agent-test--with-alert-dir
    (templedb-agent-test--drop-alert
     "20260101T000001.0-s1-done-1-0.json"
     '((schema . 1) (kind . "done") (urgency . "normal")
       (title . "Agent finished — templedb") (body . "Done\nsession #1")))
    (templedb-agent--alert-scan t)
    (should (= 1 (length templedb-agent--alert-log)))
    ;; A second scan must not re-deliver the same file.
    (templedb-agent--alert-scan t)
    (should (= 1 (length templedb-agent--alert-log)))))

(ert-deftest templedb-agent-test/alert-seed-scan-delivers-nothing ()
  "Starting the watch must not replay history."
  (templedb-agent-test--with-alert-dir
    (templedb-agent-test--drop-alert
     "20260101T000001.0-s1-done-1-0.json"
     '((schema . 1) (kind . "done") (title . "t") (body . "b")))
    (templedb-agent--alert-scan nil)
    (should (null templedb-agent--alert-log))
    ;; ...and the seeded file is not delivered by a later scan either.
    (templedb-agent--alert-scan t)
    (should (null templedb-agent--alert-log))))

(ert-deftest templedb-agent-test/alert-files-are-time-ordered ()
  (templedb-agent-test--with-alert-dir
    (dolist (n '("20260101T000003.0-s1-done-1-2.json"
                 "20260101T000001.0-s1-done-1-0.json"
                 "20260101T000002.0-s1-done-1-1.json"))
      (templedb-agent-test--drop-alert n '((schema . 1) (kind . "done"))))
    (should (equal (mapcar #'file-name-nondirectory
                           (templedb-agent--alert-files))
                   '("20260101T000001.0-s1-done-1-0.json"
                     "20260101T000002.0-s1-done-1-1.json"
                     "20260101T000003.0-s1-done-1-2.json")))))

(ert-deftest templedb-agent-test/alert-ignores-producer-tempfiles ()
  "The producer's in-flight tempfile has no .json suffix and must be
invisible to the watcher."
  (templedb-agent-test--with-alert-dir
    (with-temp-file (expand-file-name ".tmp-alert-abc123"
                                      templedb-agent-alert-dir)
      (insert "{\"half\": "))
    (should (null (templedb-agent--alert-files)))
    (templedb-agent--alert-scan t)
    (should (null templedb-agent--alert-log))))

(ert-deftest templedb-agent-test/alert-future-schema-is-skipped ()
  (templedb-agent-test--with-alert-dir
    (templedb-agent-test--drop-alert
     "20260101T000001.0-s1-done-1-0.json"
     `((schema . ,(1+ templedb-agent--alert-schema))
       (kind . "done") (title . "t") (body . "b")))
    (cl-letf (((symbol-function 'message) #'ignore))
      (templedb-agent--alert-scan t))
    (should (null templedb-agent--alert-log))))

(ert-deftest templedb-agent-test/alert-garbage-file-does-not-break-the-scan ()
  (templedb-agent-test--with-alert-dir
    (with-temp-file (expand-file-name "20260101T000001.0-bad.json"
                                      templedb-agent-alert-dir)
      (insert "{not json"))
    (templedb-agent-test--drop-alert
     "20260101T000002.0-s1-done-1-0.json"
     '((schema . 1) (kind . "done") (title . "t") (body . "b")))
    (cl-letf (((symbol-function 'message) #'ignore))
      (templedb-agent--alert-scan t))
    (should (= 1 (length templedb-agent--alert-log)))))

(ert-deftest templedb-agent-test/alert-kind-filter-applies-to-delivery-only ()
  "An out-of-filter kind is still collected, just not announced."
  (templedb-agent-test--with-alert-dir
    (let ((templedb-agent-alert-kinds '("failed"))
          (templedb-agent-alert-method 'echo)
          (said nil))
      (templedb-agent-test--drop-alert
       "20260101T000001.0-s1-done-1-0.json"
       '((schema . 1) (kind . "done") (title . "t") (body . "b")))
      (cl-letf (((symbol-function 'message)
                 (lambda (&rest args) (setq said (apply #'format args)))))
        (templedb-agent--alert-scan t))
      (should (= 1 (length templedb-agent--alert-log)))
      (should (null said)))))

(ert-deftest templedb-agent-test/alert-echo-method-announces ()
  (templedb-agent-test--with-alert-dir
    (let ((templedb-agent-alert-method 'echo)
          (said nil))
      (templedb-agent-test--drop-alert
       "20260101T000001.0-s1-failed-1-0.json"
       '((schema . 1) (kind . "failed") (urgency . "critical")
         (title . "Agent failed — templedb")
         (body . "exit 1\nsession #1 · templedb")))
      (cl-letf (((symbol-function 'message)
                 (lambda (&rest args) (setq said (apply #'format args)))))
        (templedb-agent--alert-scan t))
      (should said)
      (should (string-match-p "Agent failed" said))
      ;; Only the first body line goes in the echo area.
      (should-not (string-match-p "\n" said)))))

(ert-deftest templedb-agent-test/alert-desktop-falls-back-to-echo ()
  "When no notification transport works, the user still gets told."
  (templedb-agent-test--with-alert-dir
    (let ((templedb-agent-alert-method 'desktop)
          (said nil))
      (templedb-agent-test--drop-alert
       "20260101T000001.0-s1-ask-1-0.json"
       '((schema . 1) (kind . "ask") (urgency . "critical")
         (title . "Agent needs you — templedb") (body . "Ship it or hold?")))
      (cl-letf (((symbol-function 'templedb-agent--alert-desktop)
                 (lambda (&rest _) nil))
                ((symbol-function 'message)
                 (lambda (&rest args) (setq said (apply #'format args)))))
        (templedb-agent--alert-scan t))
      (should said)
      (should (string-match-p "Agent needs you" said)))))

(ert-deftest templedb-agent-test/alert-forget-missing-prunes-seen-table ()
  "The producer deletes old alerts; the seen-table must not grow forever."
  (templedb-agent-test--with-alert-dir
    (let ((path (templedb-agent-test--drop-alert
                 "20260101T000001.0-s1-done-1-0.json"
                 '((schema . 1) (kind . "done")))))
      (templedb-agent--alert-scan t)
      (should (= 1 (hash-table-count templedb-agent--alert-seen)))
      (delete-file path)
      (templedb-agent--alert-forget-missing)
      (should (= 0 (hash-table-count templedb-agent--alert-seen))))))

(ert-deftest templedb-agent-test/alert-missing-dir-is-not-an-error ()
  (let ((templedb-agent-alert-dir "/nonexistent/templedb-alerts-nope"))
    (should (null (templedb-agent--alert-files)))
    (should (null (templedb-agent--alert-scan t)))))

(ert-deftest templedb-agent-test/alerts-mode-and-commands-exist ()
  (should (fboundp 'templedb-agent-alerts-mode))
  (should (commandp 'templedb-agent-alerts-mode))
  (should (boundp 'templedb-agent-alerts-mode))
  ;; Global, not buffer-local: one watcher serves every session.
  (should-not (local-variable-if-set-p 'templedb-agent-alerts-mode))
  (should (commandp 'templedb-agent-alerts-show))
  (should (commandp 'templedb-agent-alerts-clear)))

(ert-deftest templedb-agent-test/alerts-show-renders-without-a-watch ()
  (templedb-agent-test--with-alert-dir
    (templedb-agent-test--drop-alert
     "20260101T000001.0-s1-done-1-0.json"
     '((schema . 1) (kind . "done") (created_at . "2026-01-01T00:00:01")
       (title . "Agent finished — templedb") (body . "Done\nsession #1")))
    (cl-letf (((symbol-function 'display-buffer) #'ignore))
      (templedb-agent-alerts-show))
    (with-current-buffer "*Temple Agent Alerts*"
      (let ((text (buffer-substring-no-properties (point-min) (point-max))))
        (should (string-match-p "Agent finished" text))
        (should (string-match-p "\\[done\\]" text))
        ;; Multi-line bodies are flattened so one alert is one entry.
        (should (string-match-p "Done · session #1" text))))
    (kill-buffer "*Temple Agent Alerts*")))

(provide 'test-templedb-agent)
;;; test-templedb-agent.el ends here
