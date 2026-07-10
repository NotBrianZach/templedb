;;; templedb-env.el --- Environment variables and secrets for TempleDB -*- lexical-binding: t; -*-

;; Copyright (C) 2026 TempleDB Contributors

;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1") (transient "0.3.0"))
;; Keywords: tools

;;; Commentary:

;; Manage environment variables, secrets, and variable tags.
;; Equivalent to GUI /env, /vars, /secrets pages.
;;
;; Entry points:
;;   M-x templedb-env         - Main transient menu
;;   M-x templedb-var-list    - List vars for a project
;;   M-x templedb-var-set     - Set a variable
;;   M-x templedb-secret-list - List secrets

;;; Code:

(require 'json)
(require 'transient)

(defgroup templedb-env nil
  "TempleDB environment variable management."
  :group 'tools
  :prefix "templedb-env-")

(defcustom templedb-env-executable "templedb"
  "Path to the templedb executable."
  :type 'string
  :group 'templedb-env)

;;; Utilities

(defun templedb-env--run (&rest args)
  "Run templedb ARGS and return output."
  (with-temp-buffer
    (let ((exit-code (apply #'call-process templedb-env-executable nil t nil args)))
      (if (zerop exit-code)
          (buffer-string)
        (error "templedb failed: %s" (buffer-string))))))

(defun templedb-env--project-list ()
  "Get project slugs."
  (let ((output (templedb-env--run "project" "list" "--format" "json")))
    (condition-case nil
        (mapcar (lambda (p) (alist-get 'slug p))
                (append (json-read-from-string output) nil))
      (error nil))))

(defun templedb-env--read-project (&optional prompt)
  "Prompt for project with PROMPT."
  (completing-read (or prompt "Project: ") (templedb-env--project-list) nil t))

;;; Var List Buffer

(defvar templedb-env--list-project nil)
(defvar templedb-env--list-scope nil)

(defvar templedb-var-list-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "s") #'templedb-var-set-interactive)
    (define-key map (kbd "d") #'templedb-var-delete-at-point)
    (define-key map (kbd "e") #'templedb-var-edit-at-point)
    (define-key map (kbd "g") #'templedb-var-list-refresh)
    (define-key map (kbd "E") #'templedb-var-export)
    (define-key map (kbd "t") #'templedb-var-tag-transient)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap for var list mode.")

(define-derived-mode templedb-var-list-mode special-mode "TDB-Vars"
  "Mode for browsing TempleDB variables.

\\{templedb-var-list-mode-map}"
  (setq truncate-lines t))

(defun templedb-var-list-refresh ()
  "Refresh the variable list."
  (interactive)
  (let* ((project (buffer-local-value 'templedb-env--list-project (current-buffer)))
         (inhibit-read-only t)
         (args (list "var" "list")))
    (when project (setq args (append args (list project))))
    (when templedb-env--list-scope
      (setq args (append args (list (format "--%s" templedb-env--list-scope)))))
    (erase-buffer)
    (insert (propertize (format "Variables%s\n"
                                (if project (format ": %s" project) " (all)"))
                        'face 'bold))
    (insert (propertize (concat "s=set d=delete e=edit E=export t=tags g=refresh\n\n")
                        'face 'shadow))
    (let ((output (apply #'templedb-env--run args)))
      (dolist (line (split-string output "\n" t))
        (let ((trimmed (string-trim line)))
          (cond
           ((string-match "^\\([A-Za-z_][A-Za-z0-9_]*\\)\\s*=\\s*\\(.*\\)" trimmed)
            (let ((key (match-string 1 trimmed))
                  (val (match-string 2 trimmed)))
              (insert (propertize key 'face 'font-lock-variable-name-face
                                  'templedb-var-key key)
                      " = "
                      (propertize val 'face 'font-lock-string-face)
                      "\n")))
           ((not (string-empty-p trimmed))
            (insert trimmed "\n"))))))
    (goto-char (point-min))))

;;;###autoload
(defun templedb-var-list (&optional project)
  "List variables for PROJECT."
  (interactive (list (templedb-env--read-project)))
  (let ((buf (get-buffer-create (format "*templedb-vars: %s*" (or project "all")))))
    (with-current-buffer buf
      (templedb-var-list-mode)
      (setq-local templedb-env--list-project project)
      (templedb-var-list-refresh))
    (switch-to-buffer buf)))

;;; Var Operations

(defun templedb-var--key-at-point ()
  "Get variable key at point."
  (get-text-property (point) 'templedb-var-key))

(defun templedb-var-set-interactive ()
  "Set a variable interactively."
  (interactive)
  (let* ((project (or templedb-env--list-project (templedb-env--read-project)))
         (key (read-string "Variable name: "))
         (value (read-string (format "%s = " key))))
    (templedb-env--run "var" "set" project key value)
    (message "Set %s = %s" key value)
    (when (derived-mode-p 'templedb-var-list-mode)
      (templedb-var-list-refresh))))

;;;###autoload
(defun templedb-var-set (project key value)
  "Set KEY=VALUE for PROJECT."
  (interactive
   (list (templedb-env--read-project)
         (read-string "Key: ")
         (read-string "Value: ")))
  (templedb-env--run "var" "set" project key value)
  (message "Set %s = %s" key value))

(defun templedb-var-delete-at-point ()
  "Delete variable at point."
  (interactive)
  (if-let ((key (templedb-var--key-at-point)))
      (let ((project (or templedb-env--list-project (templedb-env--read-project))))
        (when (yes-or-no-p (format "Delete %s? " key))
          (templedb-env--run "var" "unset" project key)
          (message "Deleted: %s" key)
          (templedb-var-list-refresh)))
    (message "No variable at point")))

(defun templedb-var-edit-at-point ()
  "Edit variable at point."
  (interactive)
  (if-let ((key (templedb-var--key-at-point)))
      (let* ((project (or templedb-env--list-project (templedb-env--read-project)))
             (current (string-trim (templedb-env--run "var" "get" project key)))
             (new-val (read-string (format "%s = " key) current)))
        (templedb-env--run "var" "set" project key new-val)
        (message "Updated %s" key)
        (templedb-var-list-refresh))
    (message "No variable at point")))

(defun templedb-var-export ()
  "Export variables."
  (interactive)
  (let* ((project (or templedb-env--list-project (templedb-env--read-project)))
         (format (completing-read "Format: " '("shell" "dotenv" "json") nil t))
         (output (templedb-env--run "var" "export" project "--format" format))
         (buf (get-buffer-create (format "*templedb-export: %s*" project))))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert output))
      (setq buffer-read-only t)
      (goto-char (point-min))
      (local-set-key (kbd "q") #'quit-window))
    (display-buffer buf)))

;;; Tags

(transient-define-prefix templedb-var-tag-transient ()
  "Variable tag operations."
  ["Tags"
   ("l" "List tags" templedb-var-tag-list)
   ("a" "Add project to tag" templedb-var-tag-add)
   ("r" "Remove project from tag" templedb-var-tag-remove)])

(defun templedb-var-tag-list ()
  "List variable tags."
  (interactive)
  (let ((output (templedb-env--run "var" "tag" "list")))
    (message "%s" (string-trim output))))

(defun templedb-var-tag-add (tag project)
  "Add PROJECT to TAG."
  (interactive
   (list (read-string "Tag name: ")
         (templedb-env--read-project "Add project: ")))
  (templedb-env--run "var" "tag" "add" tag project)
  (message "Added %s to tag %s" project tag))

(defun templedb-var-tag-remove (tag project)
  "Remove PROJECT from TAG."
  (interactive
   (list (read-string "Tag name: ")
         (templedb-env--read-project "Remove project: ")))
  (templedb-env--run "var" "tag" "remove" tag project)
  (message "Removed %s from tag %s" project tag))

;;; Secrets

;;;###autoload
(defun templedb-secret-list (&optional project)
  "List secrets for PROJECT."
  (interactive (list (templedb-env--read-project)))
  (let ((output (templedb-env--run "var" "list" project "--secret")))
    (let ((buf (get-buffer-create (format "*templedb-secrets: %s*" project))))
      (with-current-buffer buf
        (let ((inhibit-read-only t))
          (erase-buffer)
          (insert (propertize (format "Secrets: %s\n\n" project) 'face 'bold))
          (insert output))
        (setq buffer-read-only t)
        (goto-char (point-min))
        (local-set-key (kbd "q") #'quit-window))
      (display-buffer buf))))

;;;###autoload
(defun templedb-secret-set (project key value)
  "Set secret KEY=VALUE for PROJECT."
  (interactive
   (list (templedb-env--read-project)
         (read-string "Secret key: ")
         (read-passwd "Secret value: ")))
  (templedb-env--run "var" "set" project key value "--secret")
  (message "Secret set: %s" key))

;;; Main Transient

;;;###autoload
(transient-define-prefix templedb-env ()
  "TempleDB environment management."
  ["Variables"
   ("l" "List vars" templedb-var-list)
   ("s" "Set var" templedb-var-set)
   ("e" "Export vars" templedb-var-export)]
  ["Secrets"
   ("S" "List secrets" templedb-secret-list)
   ("K" "Set secret" templedb-secret-set)]
  ["Tags"
   ("t" "Tag operations" templedb-var-tag-transient)])

(provide 'templedb-env)

;;; templedb-env.el ends here
