;;; templedb-vibe.el --- Vibe Coding Quiz Interface for TempleDB -*- lexical-binding: t; -*-

;; Copyright (C) 2026 TempleDB Contributors

;; Author: TempleDB Contributors
;; URL: https://github.com/yourusername/templedb
;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1") (request "0.3.0") (websocket "1.13"))
;; Keywords: tools, ai, learning

;; This file is not part of GNU Emacs.

;;; Commentary:

;; TempleDB Vibe Coding - Interactive quiz interface for understanding AI-generated code.
;;
;; Usage:
;;   M-x templedb-vibe-start - Start a vibe coding session
;;   M-x templedb-vibe-answer - Answer current question
;;   M-x templedb-vibe-skip - Skip current question
;;   M-x templedb-vibe-stop - End session and show results
;;
;; Features:
;;   - Real-time quiz questions as you code with Claude
;;   - Side-by-side quiz display
;;   - Inline question markers in code
;;   - Progress tracking
;;   - Immediate feedback

;;; Code:

(require 'json)
(require 'request)
(require 'websocket)

(defgroup templedb-vibe nil
  "Vibe Coding quiz interface for TempleDB."
  :group 'tools
  :prefix "templedb-vibe-")

(defcustom templedb-vibe-api-url "http://localhost:8765"
  "URL of the TempleDB vibe API server."
  :type 'string
  :group 'templedb-vibe)

(defcustom templedb-vibe-auto-show t
  "Automatically show questions when they arrive."
  :type 'boolean
  :group 'templedb-vibe)

(defcustom templedb-vibe-window-position 'right
  "Position of the vibe quiz window."
  :type '(choice (const :tag "Right" right)
                 (const :tag "Bottom" bottom)
                 (const :tag "Left" left))
  :group 'templedb-vibe)

(defcustom templedb-vibe-window-size 40
  "Size of the vibe quiz window (width for side, height for bottom)."
  :type 'integer
  :group 'templedb-vibe)

(defcustom templedb-vibe-show-inline-hints t
  "Show inline hints in code for questions related to specific lines."
  :type 'boolean
  :group 'templedb-vibe)

;;; Variables

(defvar templedb-vibe--session-id nil
  "Current vibe coding session ID.")

(defvar templedb-vibe--session-token nil
  "Current session authentication token.")

(defvar templedb-vibe--websocket nil
  "WebSocket connection to vibe server.")

(defvar templedb-vibe--buffer "*TempleDB Vibe*"
  "Name of the vibe quiz buffer.")

(defvar templedb-vibe--current-question nil
  "Currently displayed question.")

(defvar templedb-vibe--question-queue '()
  "Queue of pending questions.")

(defvar templedb-vibe--stats '((correct . 0) (total . 0))
  "Session statistics.")

(defvar templedb-vibe--overlays '()
  "List of overlays for inline question markers.")

;;; Core Functions

(defun templedb-vibe-start (project)
  "Start a vibe coding session for PROJECT."
  (interactive "sProject: ")
  (when templedb-vibe--session-id
    (user-error "Vibe session already active. Use templedb-vibe-stop first"))

  ;; Create session
  (request
    (concat templedb-vibe-api-url "/api/vibe/start")
    :type "POST"
    :data (json-encode `((project . ,project)
                         (developer_id . ,(user-login-name))))
    :headers '(("Content-Type" . "application/json"))
    :parser 'json-read
    :success (cl-function
              (lambda (&key data &allow-other-keys)
                (setq templedb-vibe--session-id (alist-get 'session_id data))
                (setq templedb-vibe--session-token (alist-get 'token data))
                (templedb-vibe--setup-ui)
                (templedb-vibe--connect-websocket)
                (message "Vibe coding session started! ID: %s" templedb-vibe--session-id)))
    :error (cl-function
            (lambda (&key error-thrown &allow-other-keys)
              (message "Failed to start vibe session: %S" error-thrown)))))

(defun templedb-vibe-stop ()
  "Stop the current vibe coding session and show results."
  (interactive)
  (unless templedb-vibe--session-id
    (user-error "No active vibe session"))

  ;; Close websocket
  (when templedb-vibe--websocket
    (websocket-close templedb-vibe--websocket))

  ;; Get results
  (request
    (concat templedb-vibe-api-url "/api/vibe/stop/" (number-to-string templedb-vibe--session-id))
    :type "POST"
    :headers `(("Authorization" . ,(concat "Bearer " templedb-vibe--session-token)))
    :parser 'json-read
    :success (cl-function
              (lambda (&key data &allow-other-keys)
                (templedb-vibe--show-results data)
                (templedb-vibe--cleanup)))
    :error (cl-function
            (lambda (&key error-thrown &allow-other-keys)
              (message "Failed to stop session: %S" error-thrown)
              (templedb-vibe--cleanup)))))

(defun templedb-vibe-answer (answer)
  "Submit ANSWER to current question."
  (interactive
   (list
    (if (eq (alist-get 'question_type templedb-vibe--current-question) 'multiple_choice)
        (completing-read "Answer: "
                        (alist-get 'options templedb-vibe--current-question))
      (read-string "Answer: "))))

  (unless templedb-vibe--current-question
    (user-error "No active question"))

  (let ((question-id (alist-get 'id templedb-vibe--current-question)))
    (request
      (concat templedb-vibe-api-url "/api/vibe/answer")
      :type "POST"
      :data (json-encode `((session_id . ,templedb-vibe--session-id)
                          (question_id . ,question-id)
                          (answer . ,answer)))
      :headers `(("Content-Type" . "application/json")
                ("Authorization" . ,(concat "Bearer " templedb-vibe--session-token)))
      :parser 'json-read
      :success (cl-function
                (lambda (&key data &allow-other-keys)
                  (templedb-vibe--show-feedback data)
                  (templedb-vibe--next-question)))
      :error (cl-function
              (lambda (&key error-thrown &allow-other-keys)
                (message "Failed to submit answer: %S" error-thrown))))))

(defun templedb-vibe-skip ()
  "Skip the current question."
  (interactive)
  (templedb-vibe--next-question)
  (message "Question skipped"))

(defun templedb-vibe-show-progress ()
  "Show current session progress."
  (interactive)
  (let* ((correct (alist-get 'correct templedb-vibe--stats))
         (total (alist-get 'total templedb-vibe--stats))
         (percent (if (> total 0)
                     (* 100.0 (/ (float correct) total))
                   0)))
    (message "Progress: %d/%d (%.1f%%) | Queued: %d"
            correct total percent (length templedb-vibe--question-queue))))

;;; UI Functions

(defun templedb-vibe--setup-ui ()
  "Setup the vibe coding UI."
  (let ((buffer (get-buffer-create templedb-vibe--buffer)))
    (with-current-buffer buffer
      (templedb-vibe-mode)
      (setq buffer-read-only nil)
      (erase-buffer)
      (insert (propertize "TempleDB Vibe Coding\n" 'face 'bold)
              (propertize (make-string 40 ?─) 'face 'shadow)
              "\n\n"
              "Session started. Waiting for questions...\n\n"
              (propertize "Commands:\n" 'face 'bold)
              "  a - Answer question\n"
              "  s - Skip question\n"
              "  p - Show progress\n"
              "  q - Quit session\n")
      (setq buffer-read-only t))

    ;; Show buffer
    (pcase templedb-vibe-window-position
      ('right (display-buffer-in-side-window
               buffer '((side . right) (slot . 0))))
      ('left (display-buffer-in-side-window
              buffer '((side . left) (slot . 0))))
      ('bottom (display-buffer-in-side-window
                buffer '((side . bottom) (slot . 0)))))))

(defun templedb-vibe--show-question (question)
  "Display QUESTION in the vibe buffer."
  (setq templedb-vibe--current-question question)
  (let ((buffer (get-buffer templedb-vibe--buffer)))
    (with-current-buffer buffer
      (setq buffer-read-only nil)
      (erase-buffer)

      ;; Header
      (insert (propertize (format "Question %d\n"
                                 (1+ (alist-get 'total templedb-vibe--stats)))
                         'face '(:weight bold :height 1.2))
              (propertize (make-string 40 ?─) 'face 'shadow)
              "\n\n")

      ;; Category and difficulty
      (when-let ((category (alist-get 'category question)))
        (insert (propertize (concat "Category: " category "\n")
                           'face 'font-lock-keyword-face)))
      (when-let ((difficulty (alist-get 'difficulty question)))
        (insert (propertize (concat "Difficulty: " difficulty "\n")
                           'face 'font-lock-comment-face)))
      (insert "\n")

      ;; Code snippet
      (when-let ((snippet (alist-get 'code_snippet question)))
        (insert (propertize "Code:\n" 'face 'bold))
        (insert (propertize snippet 'face 'font-lock-string-face))
        (insert "\n\n"))

      ;; Question text
      (insert (propertize "Q: " 'face '(:foreground "blue" :weight bold))
              (alist-get 'question_text question)
              "\n\n")

      ;; Options (for multiple choice)
      (when (eq (alist-get 'question_type question) 'multiple_choice)
        (let ((options (alist-get 'options question)))
          (dotimes (i (length options))
            (insert (format "  %d. %s\n" (1+ i) (aref options i)))))
        (insert "\n"))

      ;; Learning objective
      (when-let ((objective (alist-get 'learning_objective question)))
        (insert (propertize "💡 " 'face 'success)
                (propertize objective 'face 'italic)
                "\n"))

      (insert "\n"
              (propertize "Press 'a' to answer or 's' to skip"
                         'face 'shadow))

      (setq buffer-read-only t)))

  ;; Show inline marker if related to specific file
  (when (and templedb-vibe-show-inline-hints
             (alist-get 'related_file_path question))
    (templedb-vibe--add-inline-marker question))

  ;; Notify user
  (when templedb-vibe-auto-show
    (message "New vibe question available! Press 'a' to answer"))

  ;; Play sound (optional)
  (when (fboundp 'play-sound-file)
    (ignore-errors
      (play-sound-file "/usr/share/sounds/freedesktop/stereo/message.oga"))))

(defun templedb-vibe--show-feedback (result)
  "Show feedback for answer RESULT."
  (let* ((correct (alist-get 'is_correct result))
         (explanation (alist-get 'explanation result))
         (correct-answer (alist-get 'correct_answer result)))

    ;; Update stats
    (cl-incf (alist-get 'total templedb-vibe--stats))
    (when correct
      (cl-incf (alist-get 'correct templedb-vibe--stats)))

    ;; Show feedback
    (with-current-buffer (get-buffer templedb-vibe--buffer)
      (setq buffer-read-only nil)
      (goto-char (point-max))
      (insert "\n"
              (propertize (if correct "✓ Correct!" "✗ Incorrect")
                         'face (if correct 'success 'error))
              "\n\n")

      (unless correct
        (insert (propertize "Correct answer: " 'face 'bold)
                (format "%s" correct-answer)
                "\n\n"))

      (when explanation
        (insert (propertize "Explanation:\n" 'face 'bold)
                explanation
                "\n"))

      (insert "\n"
              (propertize "Press any key to continue..." 'face 'shadow))
      (setq buffer-read-only t))

    ;; Wait for keypress
    (read-char)))

(defun templedb-vibe--show-results (results)
  "Show final session RESULTS."
  (let ((correct (alist-get 'correct results))
        (total (alist-get 'total results))
        (score (alist-get 'score results)))
    (with-current-buffer (get-buffer templedb-vibe--buffer)
      (setq buffer-read-only nil)
      (erase-buffer)

      (insert (propertize "Vibe Coding Session Complete!\n"
                         'face '(:weight bold :height 1.5))
              (propertize (make-string 40 ?═) 'face 'shadow)
              "\n\n")

      (insert (format "Score: %d/%d (%.1f%%)\n\n"
                     correct total (* 100.0 score)))

      (insert (propertize "Performance:\n" 'face 'bold))
      (templedb-vibe--draw-progress-bar score)
      (insert "\n\n")

      (when-let ((strong (alist-get 'strong_concepts results)))
        (insert (propertize "✓ Strong areas: " 'face 'success)
                (mapconcat 'identity strong ", ")
                "\n"))

      (when-let ((weak (alist-get 'weak_concepts results)))
        (insert (propertize "✗ Needs practice: " 'face 'warning)
                (mapconcat 'identity weak ", ")
                "\n"))

      (insert "\n"
              (propertize "Press 'q' to close" 'face 'shadow))
      (setq buffer-read-only t))))

(defun templedb-vibe--draw-progress-bar (score)
  "Draw a progress bar for SCORE (0.0-1.0)."
  (let* ((width 30)
         (filled (floor (* width score)))
         (empty (- width filled)))
    (insert "  ["
            (propertize (make-string filled ?█) 'face 'success)
            (make-string empty ?░)
            "]\n")))

(defun templedb-vibe--add-inline-marker (question)
  "Add inline marker for QUESTION in related file."
  (when-let* ((file-path (alist-get 'related_file_path question))
              (buffer (find-buffer-visiting file-path)))
    (with-current-buffer buffer
      (save-excursion
        ;; Try to find relevant line (simple heuristic for now)
        (goto-char (point-min))
        (let ((overlay (make-overlay (point-at-bol) (point-at-eol))))
          (overlay-put overlay 'before-string
                      (propertize "❓ " 'face '(:foreground "yellow")))
          (overlay-put overlay 'help-echo
                      (alist-get 'question_text question))
          (push overlay templedb-vibe--overlays))))))

;;; WebSocket Functions

(defun templedb-vibe--connect-websocket ()
  "Connect to vibe WebSocket for real-time updates."
  (setq templedb-vibe--websocket
        (websocket-open
         (concat (replace-regexp-in-string "^http" "ws" templedb-vibe-api-url)
                "/ws/vibe/"
                (number-to-string templedb-vibe--session-id))
         :on-message #'templedb-vibe--handle-ws-message
         :on-close #'templedb-vibe--handle-ws-close
         :on-error #'templedb-vibe--handle-ws-error)))

(defun templedb-vibe--handle-ws-message (_websocket frame)
  "Handle WebSocket FRAME message."
  (let* ((data (json-read-from-string (websocket-frame-text frame)))
         (type (alist-get 'type data)))
    (pcase type
      ("question" (templedb-vibe--handle-new-question (alist-get 'question data)))
      ("change" (message "Code change detected: %s" (alist-get 'file data)))
      ("stats" (setq templedb-vibe--stats (alist-get 'stats data)))
      (_ (message "Unknown vibe event: %s" type)))))

(defun templedb-vibe--handle-new-question (question)
  "Handle new QUESTION from WebSocket."
  (push question templedb-vibe--question-queue)
  (unless templedb-vibe--current-question
    (templedb-vibe--next-question)))

(defun templedb-vibe--handle-ws-close (_websocket)
  "Handle WebSocket close."
  (message "Vibe WebSocket disconnected"))

(defun templedb-vibe--handle-ws-error (_websocket _type _error)
  "Handle WebSocket error."
  (message "Vibe WebSocket error"))

;;; Helper Functions

(defun templedb-vibe--next-question ()
  "Show next question from queue."
  (setq templedb-vibe--current-question nil)
  (when-let ((question (pop templedb-vibe--question-queue)))
    (templedb-vibe--show-question question)))

(defun templedb-vibe--cleanup ()
  "Cleanup vibe session resources."
  (setq templedb-vibe--session-id nil)
  (setq templedb-vibe--session-token nil)
  (setq templedb-vibe--current-question nil)
  (setq templedb-vibe--question-queue '())
  (setq templedb-vibe--stats '((correct . 0) (total . 0)))

  ;; Remove overlays
  (dolist (overlay templedb-vibe--overlays)
    (delete-overlay overlay))
  (setq templedb-vibe--overlays '())

  ;; Close websocket
  (when templedb-vibe--websocket
    (websocket-close templedb-vibe--websocket)
    (setq templedb-vibe--websocket nil)))

;;; Mode Definition

(defvar templedb-vibe-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "a") 'templedb-vibe-answer)
    (define-key map (kbd "s") 'templedb-vibe-skip)
    (define-key map (kbd "p") 'templedb-vibe-show-progress)
    (define-key map (kbd "q") 'templedb-vibe-stop)
    (define-key map (kbd "?") 'templedb-vibe-help)
    map)
  "Keymap for `templedb-vibe-mode'.")

(define-derived-mode templedb-vibe-mode special-mode "Vibe"
  "Major mode for TempleDB Vibe Coding quiz interface."
  (setq-local buffer-read-only t))

(defun templedb-vibe-help ()
  "Show vibe coding help."
  (interactive)
  (message "Vibe Coding: a=answer s=skip p=progress q=quit ?=help"))

;;; Autoload

;;;###autoload
(defun templedb-vibe-start-with-claude (project)
  "Start vibe coding session for PROJECT and launch Claude Code."
  (interactive "sProject: ")
  (templedb-vibe-start project)
  ;; Launch Claude in background
  (start-process "templedb-claude" nil
                "templedb" "claude" "--from-db" "--project" project))

(provide 'templedb-vibe)

;;; templedb-vibe.el ends here
