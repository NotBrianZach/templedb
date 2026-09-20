;;; templedb-deploy.el --- Deploy pipeline for TempleDB -*- lexical-binding: t; -*-

;; Copyright (C) 2026 TempleDB Contributors

;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1") (transient "0.3.0"))
;; Keywords: tools

;;; Commentary:

;; Deploy pipeline management from Emacs.
;; Equivalent to GUI /deploy page.
;;
;; Entry points:
;;   M-x templedb-deploy          - Main deploy transient
;;   M-x templedb-deploy-run      - Deploy a project
;;   M-x templedb-deploy-history  - View deploy history
;;   M-x templedb-deploy-status   - View deploy status

;;; Code:

(require 'transient)

(defcustom templedb-deploy-executable "templedb"
  "Path to templedb."
  :type 'string
  :group 'tools)

;;; Utilities

(defun templedb-deploy--run (&rest args)
  "Run templedb ARGS."
  (with-temp-buffer
    (let ((exit-code (apply #'call-process templedb-deploy-executable nil t nil args)))
      (cons exit-code (buffer-string)))))

(defun templedb-deploy--run-ok (&rest args)
  "Run templedb ARGS, error on failure."
  (let ((result (apply #'templedb-deploy--run args)))
    (if (zerop (car result))
        (cdr result)
      (error "templedb failed: %s" (cdr result)))))

(defun templedb-deploy--project-list ()
  "Get project slugs."
  (let ((output (templedb-deploy--run-ok "project" "list" "--format" "json")))
    (condition-case nil
        (mapcar (lambda (p) (alist-get 'slug p))
                (append (json-read-from-string output) nil))
      (error nil))))

(defun templedb-deploy--read-project ()
  "Prompt for project."
  (completing-read "Project: " (templedb-deploy--project-list) nil t))

;;; Deploy Operations

;;;###autoload
(defun templedb-deploy-run (project &optional target)
  "Deploy PROJECT to TARGET."
  (interactive
   (list (templedb-deploy--read-project)
         (read-string "Target (default production): " nil nil "production")))
  (message "Deploying %s to %s..." project target)
  (let* ((args (list "deploy" "run" project "--target" target))
         (result (apply #'templedb-deploy--run args)))
    (if (zerop (car result))
        (message "Deploy succeeded:\n%s" (string-trim (cdr result)))
      (message "Deploy failed:\n%s" (string-trim (cdr result))))))

(defun templedb-deploy-run-dry (project)
  "Dry-run deploy for PROJECT."
  (interactive (list (templedb-deploy--read-project)))
  (let ((output (templedb-deploy--run-ok "deploy" "run" project "--dry-run")))
    (templedb-deploy--display "Dry Run" output)))

(defun templedb-deploy-run-all-targets (project)
  "Deploy PROJECT to all targets."
  (interactive (list (templedb-deploy--read-project)))
  (when (yes-or-no-p (format "Deploy %s to ALL targets? " project))
    (message "Deploying %s to all targets..." project)
    (let ((result (templedb-deploy--run "deploy" "run" project "--all-targets")))
      (if (zerop (car result))
          (message "Deploy succeeded:\n%s" (string-trim (cdr result)))
        (message "Deploy failed:\n%s" (string-trim (cdr result)))))))

;;; Status & History

(defun templedb-deploy--display (title output)
  "Display OUTPUT in buffer with TITLE."
  (let ((buf (get-buffer-create (format "*templedb-deploy: %s*" title))))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (propertize (format "%s\n" title) 'face 'bold))
        (insert (make-string 40 ?-) "\n\n")
        (insert output))
      (setq buffer-read-only t)
      (goto-char (point-min))
      (local-set-key (kbd "q") #'quit-window)
      (local-set-key (kbd "g") (lambda () (interactive) (message "Use deploy transient to refresh"))))
    (display-buffer buf)))

;;;###autoload
(defun templedb-deploy-status (project)
  "Show deploy status for PROJECT."
  (interactive (list (templedb-deploy--read-project)))
  (let ((output (templedb-deploy--run-ok "deploy" "status" project)))
    (templedb-deploy--display (format "Status: %s" project) output)))

;;;###autoload
(defun templedb-deploy-history (project)
  "Show deploy history for PROJECT."
  (interactive (list (templedb-deploy--read-project)))
  (let ((output (templedb-deploy--run-ok "deploy" "history" project "--limit" "20")))
    (templedb-deploy--display (format "History: %s" project) output)))

(defun templedb-deploy-stats (project)
  "Show deploy statistics for PROJECT."
  (interactive (list (templedb-deploy--read-project)))
  (let ((output (templedb-deploy--run-ok "deploy" "stats" project)))
    (templedb-deploy--display (format "Stats: %s" project) output)))

(defun templedb-deploy-health-check (project)
  "Run health check for PROJECT."
  (interactive (list (templedb-deploy--read-project)))
  (message "Running health check for %s..." project)
  (let ((output (templedb-deploy--run-ok "deploy" "health-check" project)))
    (templedb-deploy--display (format "Health: %s" project) output)))

;;; Rollback

(defun templedb-deploy-rollback (project)
  "Rollback PROJECT to previous deployment."
  (interactive (list (templedb-deploy--read-project)))
  (when (yes-or-no-p (format "Rollback %s to previous deployment? " project))
    (let* ((reason (read-string "Reason: "))
           (args (list "deploy" "rollback" project "--yes"))
           (args (if (not (string-empty-p reason))
                     (append args (list "--reason" reason))
                   args))
           (result (apply #'templedb-deploy--run args)))
      (if (zerop (car result))
          (message "Rollback succeeded: %s" (string-trim (cdr result)))
        (message "Rollback failed: %s" (string-trim (cdr result)))))))

;;; Triggers

(defun templedb-deploy-trigger-list ()
  "List deploy triggers."
  (interactive)
  (let ((output (templedb-deploy--run-ok "deploy" "trigger" "list")))
    (templedb-deploy--display "Deploy Triggers" output)))

;;; Deploy List

(defun templedb-deploy-list ()
  "List all deployed projects."
  (interactive)
  (let ((output (templedb-deploy--run-ok "deploy" "list")))
    (templedb-deploy--display "Deployed Projects" output)))

;;; NixOS Deploy

(defun templedb-deploy-nixos-rebuild (project)
  "NixOS rebuild for PROJECT."
  (interactive (list (templedb-deploy--read-project)))
  (when (yes-or-no-p (format "NixOS rebuild %s? " project))
    (message "Rebuilding NixOS for %s..." project)
    (let ((result (templedb-deploy--run "nixos" "rebuild" project "--yes")))
      (if (zerop (car result))
          (message "Rebuild succeeded")
        (message "Rebuild failed: %s" (string-trim (cdr result)))))))

(defun templedb-deploy-nixos-switch (project)
  "NixOS system switch for PROJECT."
  (interactive (list (templedb-deploy--read-project)))
  (when (yes-or-no-p (format "NixOS system-switch %s? " project))
    (message "Switching system config for %s..." project)
    (let ((result (templedb-deploy--run "nixos" "system-switch" project "--yes")))
      (if (zerop (car result))
          (message "Switch succeeded")
        (message "Switch failed: %s" (string-trim (cdr result)))))))

;;; Main Transient

;;;###autoload
(transient-define-prefix templedb-deploy ()
  "TempleDB deploy pipeline."
  ["Deploy"
   ("d" "Deploy project" templedb-deploy-run)
   ("D" "Dry run" templedb-deploy-run-dry)
   ("A" "Deploy all targets" templedb-deploy-run-all-targets)]
  ["Info"
   ("s" "Status" templedb-deploy-status)
   ("h" "History" templedb-deploy-history)
   ("S" "Statistics" templedb-deploy-stats)
   ("H" "Health check" templedb-deploy-health-check)
   ("l" "List deployed" templedb-deploy-list)]
  ["Actions"
   ("r" "Rollback" templedb-deploy-rollback)
   ("t" "Triggers" templedb-deploy-trigger-list)]
  ["NixOS"
   ("n" "NixOS rebuild" templedb-deploy-nixos-rebuild)
   ("N" "NixOS system-switch" templedb-deploy-nixos-switch)])

(provide 'templedb-deploy)

;;; templedb-deploy.el ends here
