;;; templedb-magit.el --- Magit-like interface for TempleDB -*- lexical-binding: t; -*-

;; Copyright (C) 2026 TempleDB Contributors

;; Author: TempleDB Contributors
;; URL: https://github.com/templedb/templedb
;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1") (transient "0.3.0"))
;; Keywords: tools, version-control

;; This file is not part of GNU Emacs.

;;; Commentary:

;; TempleDB Magit - Magit-like interface for TempleDB version control.
;;
;; Features:
;;   - Status buffer showing staged/modified/untracked files
;;   - Quick file editing with RET or 'e'
;;   - Stage/unstage files
;;   - Commit workflow
;;   - Diff viewing
;;   - Branch management
;;   - Integration with TempleDB CLI
;;
;; Usage:
;;   M-x templedb-magit-status - Open status buffer for current project
;;   M-x templedb-magit-status-project - Open status buffer for specific project
;;
;; Keybindings in status buffer:
;;   RET / e - Edit file at point
;;   s - Stage file at point
;;   u - Unstage file at point
;;   c - Commit staged changes
;;   d - View diff for file at point
;;   g - Refresh status
;;   q - Quit status buffer
;;   TAB - Toggle section visibility

;;; Code:

(require 'json)

(defgroup templedb-magit nil
  "Magit-like interface for TempleDB."
  :group 'tools
  :prefix "templedb-magit-")

(defcustom templedb-magit-executable "templedb"
  "Path to the templedb executable."
  :type 'string
  :group 'templedb-magit)

(defcustom templedb-magit-auto-refresh t
  "Automatically refresh status buffer after operations."
  :type 'boolean
  :group 'templedb-magit)

;;; Variables

(defvar templedb-magit--current-project nil
  "Current project slug for the status buffer.")

(defvar templedb-magit--status-data nil
  "Cached status data for current project.")

(defvar-local templedb-magit--section-overlays nil
  "List of section overlays in current buffer.")

;;; Faces

(defface templedb-magit-section-heading
  '((t :inherit magit-section-heading))
  "Face for section headings."
  :group 'templedb-magit)

(defface templedb-magit-section-heading-selection
  '((t :inherit bold))
  "Face for selected section headings."
  :group 'templedb-magit)

(defface templedb-magit-filename
  '((t :inherit magit-filename))
  "Face for filenames."
  :group 'templedb-magit)

(defface templedb-magit-diff-added
  '((t :inherit diff-added))
  "Face for added lines in diffs."
  :group 'templedb-magit)

(defface templedb-magit-diff-removed
  '((t :inherit diff-removed))
  "Face for removed lines in diffs."
  :group 'templedb-magit)

;;; Utilities

(defun templedb-magit--run-command (&rest args)
  "Run templedb command with ARGS and return output."
  (with-temp-buffer
    (let* ((exit-code (apply #'call-process templedb-magit-executable nil t nil args))
           (output (buffer-string)))
      (if (zerop exit-code)
          output
        (error "TempleDB command failed: %s" output)))))

(defun templedb-magit--run-command-json (&rest args)
  "Run templedb command with ARGS and parse JSON output."
  (let ((output (apply #'templedb-magit--run-command args)))
    (condition-case err
        (json-read-from-string output)
      (error
       (message "Failed to parse JSON: %s" output)
       nil))))

(defun templedb-magit--get-project-list ()
  "Get list of TempleDB projects."
  (templedb-magit--run-command-json "project" "list" "--format" "json"))

(defun templedb-magit--detect-project ()
  "Detect TempleDB project from current directory."
  (let* ((default-directory (or default-directory (expand-file-name "~")))
         (projects (templedb-magit--get-project-list))
         (current-dir (expand-file-name default-directory))
         (matching-project nil))
    ;; Find project whose repo_url matches current directory
    (dolist (project projects)
      (when-let ((repo-url (alist-get 'repo_url project)))
        (let ((repo-path (replace-regexp-in-string "^file://" "" repo-url)))
          (when (string-prefix-p repo-path current-dir)
            (setq matching-project (alist-get 'slug project))))))
    matching-project))

(defun templedb-magit--get-status (project)
  "Get VCS status for PROJECT."
  (templedb-magit--run-command-json "vcs" "status" project "--format" "json"))

(defun templedb-magit--stage-file (project file)
  "Stage FILE in PROJECT."
  (templedb-magit--run-command "vcs" "add" project file))

(defun templedb-magit--unstage-file (project file)
  "Unstage FILE in PROJECT."
  (templedb-magit--run-command "vcs" "reset" project file))

(defun templedb-magit--get-file-at-point ()
  "Get filename at point from status buffer."
  (get-text-property (point) 'templedb-file))

(defun templedb-magit--get-project-path (project)
  "Get filesystem path for PROJECT."
  (let* ((projects (templedb-magit--get-project-list))
         (project-data (seq-find
                        (lambda (p) (string= (alist-get 'slug p) project))
                        projects)))
    (when-let ((repo-url (alist-get 'repo_url project-data)))
      (replace-regexp-in-string "^file://" "" repo-url))))

;;; File Operations

(defun templedb-magit-edit-file ()
  "Edit file at point in current buffer."
  (interactive)
  (if-let ((file (templedb-magit--get-file-at-point)))
      (when templedb-magit--current-project
        (let* ((project-path (templedb-magit--get-project-path templedb-magit--current-project))
               (full-path (expand-file-name file project-path)))
          (if (file-exists-p full-path)
              (find-file full-path)
            (error "File does not exist: %s" full-path))))
    (message "No file at point")))

(defun templedb-magit-show-file ()
  "Show file at point in read-only buffer."
  (interactive)
  (if-let ((file (templedb-magit--get-file-at-point)))
      (when templedb-magit--current-project
        (let* ((content (templedb-magit--run-command "file" "show"
                                                      templedb-magit--current-project
                                                      file))
               (buf (get-buffer-create (format "*templedb: %s*" file))))
          (with-current-buffer buf
            (erase-buffer)
            (insert content)
            (setq buffer-read-only t)
            (goto-char (point-min))
            (set-auto-mode t))
          (display-buffer buf)))
    (message "No file at point")))

(defun templedb-magit-stage-file ()
  "Stage file at point."
  (interactive)
  (if-let ((file (templedb-magit--get-file-at-point)))
      (progn
        (templedb-magit--stage-file templedb-magit--current-project file)
        (message "Staged: %s" file)
        (when templedb-magit-auto-refresh
          (templedb-magit-refresh)))
    (message "No file at point")))

(defun templedb-magit-unstage-file ()
  "Unstage file at point."
  (interactive)
  (if-let ((file (templedb-magit--get-file-at-point)))
      (progn
        (templedb-magit--unstage-file templedb-magit--current-project file)
        (message "Unstaged: %s" file)
        (when templedb-magit-auto-refresh
          (templedb-magit-refresh)))
    (message "No file at point")))

;;; Commit

(defun templedb-magit-commit ()
  "Commit staged changes."
  (interactive)
  (let* ((author (or (getenv "GIT_AUTHOR_NAME") "Unknown Author"))
         (message (read-string "Commit message: ")))
    (when (string-empty-p message)
      (user-error "Commit message cannot be empty"))
    (templedb-magit--run-command "vcs" "commit" templedb-magit--current-project
                                  "--message" message
                                  "--author" author)
    (message "Committed!")
    (when templedb-magit-auto-refresh
      (templedb-magit-refresh))))

;;; Status Buffer

(defun templedb-magit--insert-section (title items &optional staged)
  "Insert a section with TITLE and ITEMS. STAGED indicates if files are staged."
  (when items
    (insert (propertize (format "%s (%d)\n" title (length items))
                        'face 'templedb-magit-section-heading))
    (dolist (item items)
      (insert (propertize (format "  %s\n" item)
                          'face 'templedb-magit-filename
                          'templedb-file item
                          'templedb-staged staged)))))

(defun templedb-magit-refresh ()
  "Refresh status buffer."
  (interactive)
  (when templedb-magit--current-project
    (let ((inhibit-read-only t)
          (status (templedb-magit--get-status templedb-magit--current-project)))
      (setq templedb-magit--status-data status)
      (erase-buffer)
      (insert (propertize (format "TempleDB Status: %s\n\n" templedb-magit--current-project)
                          'face 'bold))

      ;; Staged files
      (when-let ((staged (alist-get 'staged status)))
        (templedb-magit--insert-section "Staged changes" staged t))

      ;; Modified files
      (when-let ((modified (alist-get 'modified status)))
        (templedb-magit--insert-section "Modified" modified nil))

      ;; Untracked files
      (when-let ((untracked (alist-get 'untracked status)))
        (templedb-magit--insert-section "Untracked" untracked nil))

      (when (and (not (alist-get 'staged status))
                 (not (alist-get 'modified status))
                 (not (alist-get 'untracked status)))
        (insert "\nWorking directory clean.\n"))

      (goto-char (point-min)))))

(defvar templedb-magit-status-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") 'templedb-magit-edit-file)
    (define-key map (kbd "e") 'templedb-magit-edit-file)
    (define-key map (kbd "v") 'templedb-magit-show-file)
    (define-key map (kbd "s") 'templedb-magit-stage-file)
    (define-key map (kbd "u") 'templedb-magit-unstage-file)
    (define-key map (kbd "c") 'templedb-magit-commit)
    (define-key map (kbd "g") 'templedb-magit-refresh)
    (define-key map (kbd "q") 'quit-window)
    map)
  "Keymap for TempleDB Magit status mode.")

(define-derived-mode templedb-magit-status-mode special-mode "TempleDB-Magit"
  "Major mode for TempleDB Magit status buffer.

\\{templedb-magit-status-mode-map}"
  (setq truncate-lines t)
  (setq buffer-read-only t))

;;; Commands

;;;###autoload
(defun templedb-magit-status ()
  "Show TempleDB status for current project (auto-detected)."
  (interactive)
  (if-let ((project (templedb-magit--detect-project)))
      (templedb-magit-status-project project)
    (call-interactively 'templedb-magit-status-project)))

;;;###autoload
(defun templedb-magit-status-project (project)
  "Show TempleDB status for PROJECT."
  (interactive
   (list (completing-read "Project: "
                          (mapcar (lambda (p) (alist-get 'slug p))
                                  (templedb-magit--get-project-list))
                          nil t)))
  (let ((buf (get-buffer-create (format "*templedb-magit: %s*" project))))
    (with-current-buffer buf
      (templedb-magit-status-mode)
      (setq templedb-magit--current-project project)
      (templedb-magit-refresh))
    (switch-to-buffer buf)))

;;;###autoload
(defun templedb-magit-file-edit (project file-path)
  "Edit FILE-PATH from PROJECT in current buffer."
  (interactive
   (list (completing-read "Project: "
                          (mapcar (lambda (p) (alist-get 'slug p))
                                  (templedb-magit--get-project-list))
                          nil t)
         (read-string "File path: ")))
  (let* ((project-path (templedb-magit--get-project-path project))
         (full-path (expand-file-name file-path project-path)))
    (if (file-exists-p full-path)
        (find-file full-path)
      (error "File does not exist: %s" full-path))))

(provide 'templedb-magit)

;;; templedb-magit.el ends here
