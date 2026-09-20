;;; templedb-fleet.el --- Fleet sync and systemd for TempleDB -*- lexical-binding: t; -*-

;; Copyright (C) 2026 TempleDB Contributors

;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1") (transient "0.3.0"))
;; Keywords: tools

;;; Commentary:

;; Fleet sync (probe, compare, push DB) and systemd management.
;; Equivalent to GUI /fleet-sync and /systemd pages.
;;
;; Entry points:
;;   M-x templedb-fleet          - Fleet transient menu
;;   M-x templedb-fleet-status   - Show fleet status
;;   M-x templedb-systemd        - Systemd transient menu
;;   M-x templedb-systemd-list   - List managed services

;;; Code:

(require 'transient)

(defcustom templedb-fleet-executable "templedb"
  "Path to templedb."
  :type 'string
  :group 'tools)

;;; Utilities

(defun templedb-fleet--run (&rest args)
  "Run templedb ARGS."
  (with-temp-buffer
    (let ((exit-code (apply #'call-process templedb-fleet-executable nil t nil args)))
      (cons exit-code (buffer-string)))))

(defun templedb-fleet--run-ok (&rest args)
  "Run templedb ARGS, error on failure."
  (let ((result (apply #'templedb-fleet--run args)))
    (if (zerop (car result))
        (cdr result)
      (error "templedb failed: %s" (cdr result)))))

(defun templedb-fleet--display (title output)
  "Display OUTPUT in buffer with TITLE."
  (let ((buf (get-buffer-create (format "*templedb-fleet: %s*" title))))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (propertize (format "%s\n" title) 'face 'bold))
        (insert (make-string 40 ?-) "\n\n")
        (insert output))
      (setq buffer-read-only t)
      (goto-char (point-min))
      (local-set-key (kbd "q") #'quit-window))
    (display-buffer buf)))

;;; Fleet Status

;;;###autoload
(defun templedb-fleet-status ()
  "Show fleet deployment status."
  (interactive)
  (let ((output (templedb-fleet--run-ok "deploy" "fleet" "status")))
    (templedb-fleet--display "Fleet Status" output)))

;;; Fleet Deploy

(defun templedb-fleet-deploy (machine)
  "Deploy to MACHINE."
  (interactive "sMachine name: ")
  (when (yes-or-no-p (format "Deploy to %s? " machine))
    (message "Deploying to %s..." machine)
    (let ((result (templedb-fleet--run "deploy" "fleet" "deploy" machine)))
      (if (zerop (car result))
          (message "Deploy to %s succeeded" machine)
        (templedb-fleet--display (format "Deploy Failed: %s" machine) (cdr result))))))

(defun templedb-fleet-deploy-all ()
  "Deploy to all machines."
  (interactive)
  (when (yes-or-no-p "Deploy to ALL machines? ")
    (message "Deploying to all machines...")
    (let ((result (templedb-fleet--run "deploy" "fleet" "deploy" "--all")))
      (if (zerop (car result))
          (message "Fleet deploy succeeded")
        (templedb-fleet--display "Fleet Deploy Failed" (cdr result))))))

(defun templedb-fleet-deploy-tagged (tag)
  "Deploy to machines with TAG."
  (interactive "sTag: ")
  (when (yes-or-no-p (format "Deploy to machines tagged '%s'? " tag))
    (message "Deploying to tag %s..." tag)
    (let ((result (templedb-fleet--run "deploy" "fleet" "deploy" "--on" tag)))
      (if (zerop (car result))
          (message "Deploy to %s succeeded" tag)
        (templedb-fleet--display (format "Deploy Failed: %s" tag) (cdr result))))))

;;; Fleet Check / Diff

(defun templedb-fleet-check (machine)
  "Check configuration for MACHINE."
  (interactive "sMachine: ")
  (let ((output (templedb-fleet--run-ok "deploy" "fleet" "check" machine)))
    (templedb-fleet--display (format "Check: %s" machine) output)))

(defun templedb-fleet-diff (machine)
  "Show config diff for MACHINE."
  (interactive "sMachine: ")
  (let ((output (templedb-fleet--run-ok "deploy" "fleet" "diff" machine)))
    (templedb-fleet--display (format "Diff: %s" machine) output)))

;;; Fleet SSH

(defun templedb-fleet-ssh (machine)
  "SSH into MACHINE via vterm."
  (interactive "sMachine: ")
  (if (fboundp 'vterm)
      (let ((vterm-buffer-name (format "*fleet-ssh: %s*" machine))
            (vterm-shell (format "templedb deploy fleet ssh %s" machine)))
        (vterm vterm-buffer-name))
    ;; Fallback to term
    (let ((buf (make-term (format "fleet-ssh-%s" machine)
                          templedb-fleet-executable nil
                          "deploy" "fleet" "ssh" machine)))
      (switch-to-buffer buf)
      (term-mode)
      (term-char-mode))))

;;; Fleet Network

(defun templedb-fleet-network ()
  "Show fleet network configuration."
  (interactive)
  (let ((output (templedb-fleet--run-ok "deploy" "fleet" "network")))
    (templedb-fleet--display "Fleet Network" output)))

(defun templedb-fleet-machine-list ()
  "List fleet machines."
  (interactive)
  (let ((output (templedb-fleet--run-ok "deploy" "fleet" "machine" "list")))
    (templedb-fleet--display "Fleet Machines" output)))

;;; Fleet Destroy

(defun templedb-fleet-destroy (machine)
  "Destroy MACHINE deployment."
  (interactive "sMachine to destroy: ")
  (when (yes-or-no-p (format "DESTROY deployment for %s? This cannot be undone! " machine))
    (when (yes-or-no-p "Are you REALLY sure? ")
      (let ((result (templedb-fleet--run "deploy" "fleet" "destroy" machine)))
        (if (zerop (car result))
            (message "Destroyed: %s" machine)
          (message "Destroy failed: %s" (string-trim (cdr result))))))))

;;; Systemd

(defvar templedb-systemd-list-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'templedb-systemd-show-at-point)
    (define-key map (kbd "s") #'templedb-systemd-start-at-point)
    (define-key map (kbd "S") #'templedb-systemd-stop-at-point)
    (define-key map (kbd "r") #'templedb-systemd-restart-at-point)
    (define-key map (kbd "j") #'templedb-systemd-journal-at-point)
    (define-key map (kbd "g") #'templedb-systemd-list-refresh)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap for systemd list buffer.")

(define-derived-mode templedb-systemd-list-mode special-mode "TDB-Systemd"
  "Mode for browsing systemd services.

\\{templedb-systemd-list-mode-map}"
  (setq truncate-lines t))

(defun templedb-systemd--unit-at-point ()
  "Get systemd unit name at point."
  (get-text-property (point) 'templedb-unit))

;;;###autoload
(defun templedb-systemd-list ()
  "List managed systemd services."
  (interactive)
  (let ((buf (get-buffer-create "*templedb-systemd*")))
    (with-current-buffer buf
      (templedb-systemd-list-mode)
      (templedb-systemd-list-refresh))
    (switch-to-buffer buf)))

(defun templedb-systemd-list-refresh ()
  "Refresh systemd list."
  (interactive)
  (let ((inhibit-read-only t)
        (output (templedb-fleet--run-ok "systemd" "list")))
    (erase-buffer)
    (insert (propertize "Systemd Services\n" 'face 'bold))
    (insert (propertize "RET=show s=start S=stop r=restart j=journal g=refresh\n\n" 'face 'shadow))
    (dolist (line (split-string output "\n" t))
      (let ((trimmed (string-trim line)))
        (when (string-match "^\\([^ ]+\\.service\\)" trimmed)
          (let ((unit (match-string 1 trimmed)))
            (insert (propertize trimmed 'templedb-unit unit) "\n")))))
    ;; If no .service lines matched, just dump raw output
    (when (= (point) (save-excursion (goto-char (point-min))
                                      (forward-line 3)
                                      (point)))
      (insert output))
    (goto-char (point-min))))

(defun templedb-systemd-show-at-point ()
  "Show details for unit at point."
  (interactive)
  (if-let ((unit (templedb-systemd--unit-at-point)))
      (let ((output (templedb-fleet--run-ok "systemd" "status" unit)))
        (templedb-fleet--display (format "Systemd: %s" unit) output))
    (message "No unit at point")))

(defun templedb-systemd-start-at-point ()
  "Start unit at point."
  (interactive)
  (if-let ((unit (templedb-systemd--unit-at-point)))
      (progn
        (templedb-fleet--run-ok "systemd" "start" unit)
        (message "Started: %s" unit)
        (templedb-systemd-list-refresh))
    (message "No unit at point")))

(defun templedb-systemd-stop-at-point ()
  "Stop unit at point."
  (interactive)
  (if-let ((unit (templedb-systemd--unit-at-point)))
      (when (yes-or-no-p (format "Stop %s? " unit))
        (templedb-fleet--run-ok "systemd" "stop" unit)
        (message "Stopped: %s" unit)
        (templedb-systemd-list-refresh))
    (message "No unit at point")))

(defun templedb-systemd-restart-at-point ()
  "Restart unit at point."
  (interactive)
  (if-let ((unit (templedb-systemd--unit-at-point)))
      (progn
        (templedb-fleet--run-ok "systemd" "restart" unit)
        (message "Restarted: %s" unit)
        (templedb-systemd-list-refresh))
    (message "No unit at point")))

(defun templedb-systemd-journal-at-point ()
  "Show journal for unit at point."
  (interactive)
  (if-let ((unit (templedb-systemd--unit-at-point)))
      (let ((output (templedb-fleet--run-ok "systemd" "journal" unit "--lines" "100")))
        (templedb-fleet--display (format "Journal: %s" unit) output))
    (message "No unit at point")))

;;; Standalone systemd commands

(defun templedb-systemd-start (unit)
  "Start UNIT."
  (interactive "sUnit name: ")
  (templedb-fleet--run-ok "systemd" "start" unit)
  (message "Started: %s" unit))

(defun templedb-systemd-stop (unit)
  "Stop UNIT."
  (interactive "sUnit name: ")
  (when (yes-or-no-p (format "Stop %s? " unit))
    (templedb-fleet--run-ok "systemd" "stop" unit)
    (message "Stopped: %s" unit)))

(defun templedb-systemd-restart (unit)
  "Restart UNIT."
  (interactive "sUnit name: ")
  (templedb-fleet--run-ok "systemd" "restart" unit)
  (message "Restarted: %s" unit))

;;; Transients

;;;###autoload
(transient-define-prefix templedb-fleet ()
  "TempleDB fleet management."
  ["Fleet Status"
   ("s" "Fleet status" templedb-fleet-status)
   ("m" "Machine list" templedb-fleet-machine-list)
   ("n" "Network config" templedb-fleet-network)]
  ["Deploy"
   ("d" "Deploy machine" templedb-fleet-deploy)
   ("D" "Deploy all" templedb-fleet-deploy-all)
   ("t" "Deploy by tag" templedb-fleet-deploy-tagged)]
  ["Inspect"
   ("c" "Check machine" templedb-fleet-check)
   ("f" "Diff machine" templedb-fleet-diff)
   ("S" "SSH into machine" templedb-fleet-ssh)]
  ["Dangerous"
   ("X" "Destroy machine" templedb-fleet-destroy)])

;;;###autoload
(transient-define-prefix templedb-systemd ()
  "TempleDB systemd management."
  ["Services"
   ("l" "List services" templedb-systemd-list)
   ("s" "Start service" templedb-systemd-start)
   ("S" "Stop service" templedb-systemd-stop)
   ("r" "Restart service" templedb-systemd-restart)])

(provide 'templedb-fleet)

;;; templedb-fleet.el ends here
