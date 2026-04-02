;;; templedb-query.el --- Natural language file queries for TempleDB -*- lexical-binding: t; -*-

;; Copyright (C) 2026 TempleDB Contributors

;; Author: TempleDB Contributors
;; URL: https://github.com/templedb/templedb
;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1"))
;; Keywords: tools, search, ai

;; This file is not part of GNU Emacs.

;;; Commentary:

;; TempleDB Query - Natural language file queries with instant editor integration.
;;
;; Query files using natural language and open them instantly in Emacs.
;; Perfect for working with large codebases and finding files by their content
;; or purpose rather than remembering exact file paths.
;;
;; Features:
;;   - Natural language queries ("authentication code", "config files")
;;   - Instant file opening in Emacs buffers
;;   - Integration with TempleDB's full-text search
;;   - Project-aware queries
;;   - Works seamlessly from vterm
;;
;; Usage:
;;   M-x templedb-query-open - Query and open files interactively
;;   M-x templedb-query-project-open - Query specific project
;;
;;   From vterm running Claude:
;;     You can just say "open the bza files with character analysis prompts"
;;     and Claude will use the templedb query-open command automatically
;;
;; Examples:
;;   - "open authentication code"
;;   - "find config files"
;;   - "show me the database migrations"
;;   - "prompts that do character analysis"

;;; Code:

(require 'json)

(defgroup templedb-query nil
  "Natural language file queries for TempleDB."
  :group 'tools
  :prefix "templedb-query-")

(defcustom templedb-query-executable "templedb"
  "Path to the templedb executable."
  :type 'string
  :group 'templedb-query)

(defcustom templedb-query-default-limit 10
  "Default maximum number of files to open from a query."
  :type 'integer
  :group 'templedb-query)

(defcustom templedb-query-auto-open t
  "Automatically open files after query (vs showing results first)."
  :type 'boolean
  :group 'templedb-query)

(defcustom templedb-query-default-project nil
  "Default project to query (nil for auto-detect)."
  :type '(choice (const :tag "Auto-detect" nil)
                 (string :tag "Project slug"))
  :group 'templedb-query)

;;; Utilities

(defun templedb-query--run-command (&rest args)
  "Run templedb command with ARGS and return output."
  (with-temp-buffer
    (let* ((exit-code (apply #'call-process templedb-query-executable nil t nil args))
           (output (buffer-string)))
      (if (zerop exit-code)
          output
        (error "TempleDB command failed: %s" output)))))

(defun templedb-query--run-command-json (&rest args)
  "Run templedb command with ARGS and parse JSON output."
  (let ((output (apply #'templedb-query--run-command args)))
    (condition-case err
        (json-read-from-string output)
      (error
       (message "Failed to parse JSON: %s" output)
       nil))))

(defun templedb-query--get-project-list ()
  "Get list of TempleDB projects."
  (templedb-query--run-command-json "project" "list" "--format" "json"))

(defun templedb-query--detect-project ()
  "Detect TempleDB project from current directory."
  (let* ((default-directory (or default-directory (expand-file-name "~")))
         (projects (templedb-query--get-project-list))
         (current-dir (expand-file-name default-directory))
         (matching-project nil))
    ;; Find project whose repo_url matches current directory
    (dolist (project projects)
      (when-let ((repo-url (alist-get 'repo_url project)))
        (let ((repo-path (replace-regexp-in-string "^file://" "" repo-url)))
          (when (string-prefix-p repo-path current-dir)
            (setq matching-project (alist-get 'slug project))))))
    matching-project))

(defun templedb-query--get-project-path (project)
  "Get filesystem path for PROJECT."
  (let* ((projects (templedb-query--get-project-list))
         (project-data (seq-find
                        (lambda (p) (string= (alist-get 'slug p) project))
                        projects)))
    (when-let ((repo-url (alist-get 'repo_url project-data)))
      (replace-regexp-in-string "^file://" "" repo-url))))

;;; Query Functions

(defun templedb-query-files (project query &optional limit)
  "Query files in PROJECT matching QUERY.
Returns list of file paths.
LIMIT is the maximum number of results (default: `templedb-query-default-limit`)."
  (let* ((limit (or limit templedb-query-default-limit))
         (results (templedb-query--run-command-json
                   "query" project query
                   "--json"
                   "--limit" (number-to-string limit))))
    (when results
      (mapcar (lambda (r) (alist-get 'file_path r))
              (append results nil)))))

(defun templedb-query-and-open-files (project query &optional limit no-select)
  "Query and open files in PROJECT matching QUERY.
Opens up to LIMIT files (default: `templedb-query-default-limit`).
If NO-SELECT is non-nil, don't select the Emacs frame."
  (let* ((limit (or limit templedb-query-default-limit))
         (project-path (templedb-query--get-project-path project))
         (file-paths (templedb-query-files project query limit)))

    (if (not file-paths)
        (message "No files found matching: %s" query)
      (let ((full-paths (mapcar (lambda (path)
                                  (expand-file-name path project-path))
                                file-paths)))
        ;; Open each file
        (dolist (path full-paths)
          (if (file-exists-p path)
              (find-file-noselect path)
            (message "Warning: File not found: %s" path)))

        ;; Switch to first file unless no-select
        (unless no-select
          (when (car full-paths)
            (switch-to-buffer (find-file-noselect (car full-paths)))))

        (message "Opened %d file(s) matching: %s" (length full-paths) query)
        full-paths))))

;;; Interactive Commands

;;;###autoload
(defun templedb-query-open (query &optional project)
  "Query and open files matching QUERY in PROJECT.
If PROJECT is nil, auto-detect from current directory or prompt."
  (interactive
   (let* ((project (or templedb-query-default-project
                      (templedb-query--detect-project)
                      (completing-read "Project: "
                                      (mapcar (lambda (p) (alist-get 'slug p))
                                              (templedb-query--get-project-list))
                                      nil t)))
          (query (read-string (format "Query [%s]: " project))))
     (list query project)))

  (if (string-empty-p query)
      (message "Query cannot be empty")
    (templedb-query-and-open-files project query)))

;;;###autoload
(defun templedb-query-project-open (project query)
  "Query and open files in PROJECT matching QUERY."
  (interactive
   (list (completing-read "Project: "
                          (mapcar (lambda (p) (alist-get 'slug p))
                                  (templedb-query--get-project-list))
                          nil t)
         (read-string "Query: ")))
  (templedb-query-and-open-files project query))

;;;###autoload
(defun templedb-query-current-project (query)
  "Query and open files in current project matching QUERY."
  (interactive "sQuery: ")
  (if-let ((project (or templedb-query-default-project
                       (templedb-query--detect-project))))
      (templedb-query-and-open-files project query)
    (message "No project detected. Use M-x templedb-query-open instead.")))

;;; Quick search functions for common patterns

;;;###autoload
(defun templedb-find-config-files (&optional project)
  "Find and open configuration files in PROJECT."
  (interactive)
  (let ((project (or project
                    templedb-query-default-project
                    (templedb-query--detect-project))))
    (templedb-query-and-open-files project "config OR configuration OR settings")))

;;;###autoload
(defun templedb-find-tests (&optional project)
  "Find and open test files in PROJECT."
  (interactive)
  (let ((project (or project
                    templedb-query-default-project
                    (templedb-query--detect-project))))
    (templedb-query-and-open-files project "test OR tests OR spec")))

;;;###autoload
(defun templedb-find-auth-code (&optional project)
  "Find and open authentication-related code in PROJECT."
  (interactive)
  (let ((project (or project
                    templedb-query-default-project
                    (templedb-query--detect-project))))
    (templedb-query-and-open-files project "auth OR authentication OR login")))

;;; Integration with completing-read

(defvar templedb-query--history nil
  "History for templedb query commands.")

;;;###autoload
(defun templedb-query-with-completion ()
  "Query and open files with query completion from history."
  (interactive)
  (let* ((project (or templedb-query-default-project
                     (templedb-query--detect-project)
                     (completing-read "Project: "
                                     (mapcar (lambda (p) (alist-get 'slug p))
                                             (templedb-query--get-project-list))
                                     nil t)))
         (query (read-string (format "Query [%s]: " project)
                            nil 'templedb-query--history)))
    (when (not (string-empty-p query))
      (templedb-query-and-open-files project query))))

;;; Emacsclient integration

;;;###autoload
(defun templedb-query-open-from-cli (project query &optional limit)
  "Open files from command line query.
This function is designed to be called from emacsclient.

Example:
  emacsclient -e \"(templedb-query-open-from-cli \\\"myproject\\\" \\\"auth code\\\" 5)\""
  (templedb-query-and-open-files project query (or limit templedb-query-default-limit)))

(provide 'templedb-query)

;;; templedb-query.el ends here
