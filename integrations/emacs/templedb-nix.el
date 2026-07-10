;;; templedb-nix.el --- NixOS config management for TempleDB -*- lexical-binding: t; -*-

;; Copyright (C) 2026 TempleDB Contributors

;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1") (transient "0.3.0"))
;; Keywords: tools

;;; Commentary:

;; NixOS configuration management from Emacs.
;; Equivalent to GUI /nix page.
;;
;; Entry points:
;;   M-x templedb-nix           - Main transient menu
;;   M-x templedb-nix-status    - Show NixOS pipeline status
;;   M-x templedb-nix-packages  - List managed packages

;;; Code:

(require 'transient)

(defcustom templedb-nix-executable "templedb"
  "Path to templedb."
  :type 'string
  :group 'tools)

;;; Utilities

(defun templedb-nix--run (&rest args)
  "Run templedb ARGS."
  (with-temp-buffer
    (let ((exit-code (apply #'call-process templedb-nix-executable nil t nil args)))
      (cons exit-code (buffer-string)))))

(defun templedb-nix--run-ok (&rest args)
  "Run templedb ARGS, error on failure."
  (let ((result (apply #'templedb-nix--run args)))
    (if (zerop (car result))
        (cdr result)
      (error "templedb failed: %s" (cdr result)))))

(defun templedb-nix--project-list ()
  "Get project slugs."
  (let ((output (templedb-nix--run-ok "project" "list" "--format" "json")))
    (condition-case nil
        (mapcar (lambda (p) (alist-get 'slug p))
                (append (json-read-from-string output) nil))
      (error nil))))

(defun templedb-nix--read-project ()
  "Prompt for project."
  (completing-read "Project: " (templedb-nix--project-list) nil t))

(defun templedb-nix--display (title output)
  "Display OUTPUT in buffer with TITLE."
  (let ((buf (get-buffer-create (format "*templedb-nix: %s*" title))))
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

;;; Status

;;;###autoload
(defun templedb-nix-status (&optional project)
  "Show NixOS pipeline status for PROJECT."
  (interactive (list (templedb-nix--read-project)))
  (let ((output (templedb-nix--run-ok "nixos" "status" project)))
    (templedb-nix--display (format "NixOS Status: %s" project) output)))

(defun templedb-nix-system-status ()
  "Show system deployment status."
  (interactive)
  (let ((output (templedb-nix--run-ok "nixos" "system-status")))
    (templedb-nix--display "System Status" output)))

(defun templedb-nix-system-history ()
  "Show system deployment history."
  (interactive)
  (let ((output (templedb-nix--run-ok "nixos" "system-history" "--limit" "20")))
    (templedb-nix--display "System History" output)))

;;; Config

(defun templedb-nix-config-list ()
  "List NixOS system configuration."
  (interactive)
  (let ((output (templedb-nix--run-ok "nixos" "config-list")))
    (templedb-nix--display "NixOS Config" output)))

(defun templedb-nix-config-get (key)
  "Get NixOS config KEY."
  (interactive "sConfig key: ")
  (let ((output (templedb-nix--run-ok "nixos" "config-get" key)))
    (message "%s = %s" key (string-trim output))))

(defun templedb-nix-config-set (key value)
  "Set NixOS config KEY to VALUE."
  (interactive "sConfig key: \nsValue: ")
  (templedb-nix--run-ok "nixos" "config-set" key value)
  (message "Set %s = %s" key value))

;;; Packages

;;;###autoload
(defun templedb-nix-packages ()
  "List managed NixOS packages."
  (interactive)
  (let ((output (templedb-nix--run-ok "nixos" "list-packages")))
    (templedb-nix--display "Managed Packages" output)))

(defun templedb-nix-packages-system ()
  "List system-scope packages."
  (interactive)
  (let ((output (templedb-nix--run-ok "nixos" "list-packages" "--scope" "system")))
    (templedb-nix--display "System Packages" output)))

(defun templedb-nix-packages-user ()
  "List user-scope packages."
  (interactive)
  (let ((output (templedb-nix--run-ok "nixos" "list-packages" "--scope" "user")))
    (templedb-nix--display "User Packages" output)))

(defun templedb-nix-add-package (project)
  "Add a CLI package to PROJECT."
  (interactive (list (templedb-nix--read-project)))
  (let ((scope (completing-read "Scope: " '("system" "user") nil t)))
    (templedb-nix--run-ok "nixos" "add-package" project "--scope" scope)
    (message "Added package for %s (%s)" project scope)))

(defun templedb-nix-remove-package (project)
  "Remove package for PROJECT."
  (interactive (list (templedb-nix--read-project)))
  (when (yes-or-no-p (format "Remove package for %s? " project))
    (templedb-nix--run-ok "nixos" "remove-package" project)
    (message "Removed package for %s" project)))

;;; Generate & Build

(defun templedb-nix-generate (project)
  "Generate NixOS modules for PROJECT."
  (interactive (list (templedb-nix--read-project)))
  (message "Generating NixOS modules for %s..." project)
  (let ((output (templedb-nix--run-ok "nixos" "generate" project)))
    (message "Generated: %s" (string-trim output))))

(defun templedb-nix-generate-all ()
  "Generate all NixOS configuration."
  (interactive)
  (message "Generating all NixOS config...")
  (let ((output (templedb-nix--run-ok "nixos" "generate-all")))
    (message "Generated: %s" (string-trim output))))

(defun templedb-nix-rebuild (project)
  "NixOS rebuild for PROJECT."
  (interactive (list (templedb-nix--read-project)))
  (when (yes-or-no-p (format "NixOS rebuild %s? " project))
    (message "Rebuilding...")
    (let ((result (templedb-nix--run "nixos" "rebuild" project "--yes")))
      (if (zerop (car result))
          (message "Rebuild succeeded")
        (templedb-nix--display "Rebuild Failed" (cdr result))))))

(defun templedb-nix-rebuild-dry (project)
  "Dry-run NixOS rebuild for PROJECT."
  (interactive (list (templedb-nix--read-project)))
  (let ((output (templedb-nix--run-ok "nixos" "rebuild" project "--dry-run")))
    (templedb-nix--display "Rebuild Dry Run" output)))

(defun templedb-nix-home-rebuild (project)
  "Rebuild home-manager for PROJECT."
  (interactive (list (templedb-nix--read-project)))
  (message "Rebuilding home-manager...")
  (let ((result (templedb-nix--run "nixos" "home-rebuild" project)))
    (if (zerop (car result))
        (message "Home rebuild succeeded")
      (templedb-nix--display "Home Rebuild Failed" (cdr result)))))

;;; Dotfiles

(defun templedb-nix-dotfiles-list ()
  "List dotfile mappings."
  (interactive)
  (let ((output (templedb-nix--run-ok "nixos" "dotfiles-list")))
    (templedb-nix--display "Dotfiles" output)))

(defun templedb-nix-dotfiles-apply ()
  "Apply dotfile symlinks."
  (interactive)
  (message "Applying dotfiles...")
  (let ((output (templedb-nix--run-ok "nixos" "dotfiles-apply" "-v")))
    (message "Applied: %s" (string-trim output))))

;;; Doctor

(defun templedb-nix-doctor (&optional project)
  "Diagnose NixOS activation problems for PROJECT."
  (interactive (list (ignore-errors (templedb-nix--read-project))))
  (let* ((args (if project (list "nixos" "doctor" project) (list "nixos" "doctor")))
         (output (apply #'templedb-nix--run-ok args)))
    (templedb-nix--display "NixOS Doctor" output)))

;;; Hosts

(defun templedb-nix-list-configs ()
  "List NixOS config projects."
  (interactive)
  (let ((output (templedb-nix--run-ok "nixos" "list-configs")))
    (templedb-nix--display "NixOS Configs" output)))

;;; Edit Templates

(defun templedb-nix-edit-template (&optional project)
  "Open .nix.template files for PROJECT in editor."
  (interactive (list (templedb-nix--read-project)))
  (let* ((args (if project (list "nixos" "edit-template" project) (list "nixos" "edit-template")))
         (result (apply #'templedb-nix--run args)))
    (if (zerop (car result))
        (message "%s" (string-trim (cdr result)))
      (message "Error: %s" (string-trim (cdr result))))))

;;; Main Transient

;;;###autoload
(transient-define-prefix templedb-nix ()
  "TempleDB NixOS configuration."
  ["Status"
   ("s" "Pipeline status" templedb-nix-status)
   ("S" "System status" templedb-nix-system-status)
   ("h" "System history" templedb-nix-system-history)
   ("D" "Doctor" templedb-nix-doctor)]
  ["Config"
   ("c" "List config" templedb-nix-config-list)
   ("C" "List NixOS configs" templedb-nix-list-configs)]
  ["Packages"
   ("p" "List packages" templedb-nix-packages)
   ("a" "Add package" templedb-nix-add-package)
   ("r" "Remove package" templedb-nix-remove-package)]
  ["Build"
   ("g" "Generate modules" templedb-nix-generate)
   ("G" "Generate all" templedb-nix-generate-all)
   ("b" "Rebuild" templedb-nix-rebuild)
   ("d" "Rebuild dry-run" templedb-nix-rebuild-dry)
   ("H" "Home rebuild" templedb-nix-home-rebuild)]
  ["Dotfiles"
   ("f" "List dotfiles" templedb-nix-dotfiles-list)
   ("F" "Apply dotfiles" templedb-nix-dotfiles-apply)])

(provide 'templedb-nix)

;;; templedb-nix.el ends here
