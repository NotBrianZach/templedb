;;; templedb-magit.el --- Magit-like interface for TempleDB -*- lexical-binding: t; -*-

;; Copyright (C) 2026 TempleDB Contributors

;; Author: TempleDB Contributors
;; URL: https://github.com/templedb/templedb
;; Version: 0.2.0
;; Package-Requires: ((emacs "27.1") (transient "0.3.0"))
;; Keywords: tools, version-control

;; This file is not part of GNU Emacs.

;;; Commentary:

;; TempleDB Magit - Magit-like interface for TempleDB version control.
;;
;; Keybindings in status buffer:
;;   RET / e - Edit file at point
;;   v       - View file read-only
;;   s       - Stage file at point
;;   S       - Stage all files
;;   u       - Unstage file at point
;;   U       - Unstage all files
;;   c       - Commit transient
;;   d       - Diff transient
;;   l       - Log transient
;;   b       - Branch transient
;;   P       - Push/Publish transient
;;   m       - Merge transient
;;   !       - CLI command popup
;;   g       - Refresh status
;;   TAB     - Toggle section
;;   q       - Quit

;;; Code:

(require 'json)
(require 'transient)

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

;;; Faces

(defface templedb-magit-section-heading
  '((t :inherit bold :foreground "#e94560"))
  "Face for section headings."
  :group 'templedb-magit)

(defface templedb-magit-filename
  '((t :inherit default))
  "Face for filenames."
  :group 'templedb-magit)

(defface templedb-magit-staged
  '((t :foreground "#4a9a6a"))
  "Face for staged files."
  :group 'templedb-magit)

(defface templedb-magit-modified
  '((t :foreground "#e9a545"))
  "Face for modified files."
  :group 'templedb-magit)

(defface templedb-magit-diff-added
  '((t :inherit diff-added))
  "Face for added lines in diffs."
  :group 'templedb-magit)

(defface templedb-magit-diff-removed
  '((t :inherit diff-removed))
  "Face for removed lines in diffs."
  :group 'templedb-magit)

(defface templedb-magit-diff-hunk
  '((t :foreground "#808098"))
  "Face for hunk headers."
  :group 'templedb-magit)

(defface templedb-magit-hash
  '((t :foreground "#4a9eff"))
  "Face for commit hashes."
  :group 'templedb-magit)

(defface templedb-magit-date
  '((t :foreground "#606080"))
  "Face for dates."
  :group 'templedb-magit)

(defface templedb-magit-branch
  '((t :foreground "#80c0ff"))
  "Face for branch names."
  :group 'templedb-magit)

;;; Variables

(defvar-local templedb-magit--current-project nil
  "Current project slug for the buffer.")

(defvar-local templedb-magit--sections nil
  "Alist of (section-name . overlay) for collapsible sections.")

(defvar-local templedb-magit--section-visibility nil
  "Alist of (section-name . visible-p) tracking collapse state.")

;;; Utilities

(defun templedb-magit--run-command (&rest args)
  "Run templedb command with ARGS and return output."
  (with-temp-buffer
    (let* ((exit-code (apply #'call-process templedb-magit-executable nil t nil args))
           (output (buffer-string)))
      (if (zerop exit-code)
          output
        (error "TempleDB command failed: %s" output)))))

(defun templedb-magit--run-command-no-error (&rest args)
  "Run templedb command with ARGS, return (exit-code . output)."
  (with-temp-buffer
    (let ((exit-code (apply #'call-process templedb-magit-executable nil t nil args)))
      (cons exit-code (buffer-string)))))

(defun templedb-magit--get-project-list ()
  "Get list of TempleDB project slugs."
  (let ((output (templedb-magit--run-command "project" "list" "--format" "json")))
    (condition-case nil
        (mapcar (lambda (p) (alist-get 'slug p))
                (append (json-read-from-string output) nil))
      (error nil))))

(defun templedb-magit--detect-project ()
  "Detect TempleDB project from current directory."
  (let* ((default-directory (or default-directory (expand-file-name "~")))
         (output (templedb-magit--run-command "project" "list" "--format" "json"))
         (projects (condition-case nil (append (json-read-from-string output) nil) (error nil)))
         (current-dir (expand-file-name default-directory)))
    (cl-loop for project in projects
             for repo-url = (alist-get 'repo_url project)
             when repo-url
             for repo-path = (replace-regexp-in-string "^file://" "" repo-url)
             when (string-prefix-p repo-path current-dir)
             return (alist-get 'slug project))))

(defun templedb-magit--get-project-path (project)
  "Get filesystem path for PROJECT."
  (let* ((output (templedb-magit--run-command "project" "list" "--format" "json"))
         (projects (condition-case nil (append (json-read-from-string output) nil) (error nil)))
         (project-data (seq-find (lambda (p) (string= (alist-get 'slug p) project)) projects)))
    (when-let ((repo-url (alist-get 'repo_url project-data)))
      (replace-regexp-in-string "^file://" "" repo-url))))

(defun templedb-magit--read-project ()
  "Prompt for a project with completion."
  (completing-read "Project: " (templedb-magit--get-project-list) nil t))

(defun templedb-magit--ensure-project ()
  "Return current project or error."
  (or templedb-magit--current-project
      (error "No project set in this buffer")))

(defun templedb-magit--get-file-at-point ()
  "Get filename at point from status buffer."
  (get-text-property (point) 'templedb-file))

(defun templedb-magit--get-file-staged-p ()
  "Get whether file at point is staged."
  (get-text-property (point) 'templedb-staged))

(defun templedb-magit--auto-refresh ()
  "Refresh if auto-refresh is enabled."
  (when templedb-magit-auto-refresh
    (templedb-magit-refresh)))

;;; Section Management

(defun templedb-magit--section-visible-p (name)
  "Return whether section NAME is visible."
  (let ((entry (assoc name templedb-magit--section-visibility)))
    (if entry (cdr entry) t)))

(defun templedb-magit--toggle-section-at-point ()
  "Toggle visibility of section at point."
  (interactive)
  (when-let ((section (get-text-property (point) 'templedb-section)))
    (let ((entry (assoc section templedb-magit--section-visibility)))
      (if entry
          (setcdr entry (not (cdr entry)))
        (push (cons section nil) templedb-magit--section-visibility)))
    (templedb-magit-refresh)))

(defun templedb-magit--insert-section (name title items &optional staged face)
  "Insert collapsible section NAME with TITLE and ITEMS.
STAGED marks files as staged. FACE is applied to filenames."
  (when items
    (let ((visible (templedb-magit--section-visible-p name))
          (indicator (if (templedb-magit--section-visible-p name) "v" ">")))
      (insert (propertize (format "%s %s (%d)\n" indicator title (length items))
                          'face 'templedb-magit-section-heading
                          'templedb-section name))
      (when visible
        (dolist (item items)
          (let ((status-char (cond (staged "  + ")
                                   (face "  M ")
                                   (t "  ? "))))
            (insert (propertize status-char
                                'face (or face 'templedb-magit-modified))
                    (propertize (format "%s\n" item)
                                'face 'templedb-magit-filename
                                'templedb-file item
                                'templedb-staged staged)))))
      (insert "\n"))))

;;; Status Buffer

(defun templedb-magit-refresh ()
  "Refresh status buffer."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (inhibit-read-only t)
         (pos (point))
         (output (templedb-magit--run-command "vcs" "status" project "--refresh"))
         (staged '()) (modified '()) (untracked '()))
    ;; Parse status output
    (dolist (line (split-string output "\n" t))
      (let ((trimmed (string-trim line)))
        (cond
         ((string-match "^staged\\s+\\(.*\\)" trimmed)
          (push (match-string 1 trimmed) staged))
         ((string-match "^modified\\s+\\(.*\\)" trimmed)
          (push (match-string 1 trimmed) modified))
         ((string-match "^added\\s+\\(.*\\)" trimmed)
          (push (match-string 1 trimmed) untracked)))))
    (setq staged (nreverse staged)
          modified (nreverse modified)
          untracked (nreverse untracked))

    (erase-buffer)
    ;; Header
    (insert (propertize (format "TempleDB: %s" project) 'face 'bold) "\n")
    ;; Branch info
    (when-let ((branch-line (cl-find-if (lambda (l) (string-match "^On branch:" l))
                                         (split-string output "\n" t))))
      (insert (propertize (string-trim branch-line) 'face 'templedb-magit-branch) "\n"))
    (insert "\n")

    ;; Sections
    (templedb-magit--insert-section 'staged "Staged changes" staged t 'templedb-magit-staged)
    (templedb-magit--insert-section 'modified "Unstaged changes" modified nil 'templedb-magit-modified)
    (templedb-magit--insert-section 'untracked "Untracked files" untracked nil nil)

    (when (and (null staged) (null modified) (null untracked))
      (insert (propertize "Working directory clean.\n" 'face 'shadow)))

    (insert "\n"
            (propertize "s" 'face 'bold) "tage  "
            (propertize "u" 'face 'bold) "nstage  "
            (propertize "c" 'face 'bold) "ommit  "
            (propertize "d" 'face 'bold) "iff  "
            (propertize "l" 'face 'bold) "og  "
            (propertize "b" 'face 'bold) "ranch  "
            (propertize "P" 'face 'bold) "ush  "
            (propertize "m" 'face 'bold) "erge  "
            (propertize "!" 'face 'bold) "cmd\n")
    (goto-char (min pos (point-max)))))

;;; File Operations

(defun templedb-magit-edit-file ()
  "Edit file at point."
  (interactive)
  (if-let ((file (templedb-magit--get-file-at-point)))
      (let* ((project-path (templedb-magit--get-project-path templedb-magit--current-project))
             (full-path (expand-file-name file project-path)))
        (if (file-exists-p full-path)
            (find-file full-path)
          (error "File does not exist: %s" full-path)))
    (message "No file at point")))

(defun templedb-magit-show-file ()
  "Show file at point read-only."
  (interactive)
  (if-let ((file (templedb-magit--get-file-at-point)))
      (let* ((project (templedb-magit--ensure-project))
             (content (templedb-magit--run-command "file" "show" project file))
             (buf (get-buffer-create (format "*templedb: %s*" file))))
        (with-current-buffer buf
          (let ((inhibit-read-only t))
            (erase-buffer)
            (insert content))
          (setq buffer-read-only t)
          (goto-char (point-min))
          (set-auto-mode t))
        (display-buffer buf))
    (message "No file at point")))

;;; Stage / Unstage

(defun templedb-magit-stage-file ()
  "Stage file at point."
  (interactive)
  (if-let ((file (templedb-magit--get-file-at-point)))
      (progn
        (templedb-magit--run-command "vcs" "add" "-p" templedb-magit--current-project file)
        (message "Staged: %s" file)
        (templedb-magit--auto-refresh))
    (message "No file at point")))

(defun templedb-magit-stage-all ()
  "Stage all files."
  (interactive)
  (templedb-magit--run-command "vcs" "add" "-p" templedb-magit--current-project "--all")
  (message "Staged all files")
  (templedb-magit--auto-refresh))

(defun templedb-magit-unstage-file ()
  "Unstage file at point."
  (interactive)
  (if-let ((file (templedb-magit--get-file-at-point)))
      (progn
        (templedb-magit--run-command "vcs" "reset" "-p" templedb-magit--current-project file)
        (message "Unstaged: %s" file)
        (templedb-magit--auto-refresh))
    (message "No file at point")))

(defun templedb-magit-unstage-all ()
  "Unstage all files."
  (interactive)
  (templedb-magit--run-command "vcs" "reset" "-p" templedb-magit--current-project "--all")
  (message "Unstaged all files")
  (templedb-magit--auto-refresh))

;;; Diff

(transient-define-prefix templedb-magit-diff ()
  "Show diffs."
  ["Diff"
   ("d" "Diff file at point" templedb-magit-diff-file)
   ("s" "Diff staged" templedb-magit-diff-staged)
   ("a" "Diff all" templedb-magit-diff-all)
   ("c" "Diff between commits" templedb-magit-diff-commits)])

(defun templedb-magit--display-diff (output &optional title)
  "Display diff OUTPUT in a buffer with TITLE."
  (let ((buf (get-buffer-create (format "*templedb-diff: %s*"
                                        (or title templedb-magit--current-project)))))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert output)
        (goto-char (point-min))
        ;; Fontify diff
        (while (not (eobp))
          (cond
           ((looking-at "^\\+")
            (put-text-property (point) (line-end-position) 'face 'templedb-magit-diff-added))
           ((looking-at "^-")
            (put-text-property (point) (line-end-position) 'face 'templedb-magit-diff-removed))
           ((looking-at "^@@")
            (put-text-property (point) (line-end-position) 'face 'templedb-magit-diff-hunk)))
          (forward-line 1))
        (goto-char (point-min)))
      (setq buffer-read-only t)
      (local-set-key (kbd "q") #'quit-window))
    (display-buffer buf)))

(defun templedb-magit-diff-file ()
  "Show diff for file at point."
  (interactive)
  (if-let ((file (templedb-magit--get-file-at-point)))
      (let* ((project (templedb-magit--ensure-project))
             (output (templedb-magit--run-command
                      "vcs" "diff" project file "--no-color")))
        (templedb-magit--display-diff output file))
    (message "No file at point")))

(defun templedb-magit-diff-staged ()
  "Show diff for all staged changes."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (output (templedb-magit--run-command
                  "vcs" "diff" project "--staged" "--no-color")))
    (templedb-magit--display-diff output "staged")))

(defun templedb-magit-diff-all ()
  "Show diff for all changes."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (output (templedb-magit--run-command
                  "vcs" "diff" project "--no-color")))
    (templedb-magit--display-diff output "all")))

(defun templedb-magit-diff-commits (commit1 commit2)
  "Show diff between COMMIT1 and COMMIT2."
  (interactive "sCommit 1: \nsCommit 2: ")
  (let* ((project (templedb-magit--ensure-project))
         (output (templedb-magit--run-command
                  "vcs" "diff" project commit1 commit2 "--no-color")))
    (templedb-magit--display-diff output (format "%s..%s" commit1 commit2))))

;;; Commit

(transient-define-prefix templedb-magit-commit-transient ()
  "Commit changes."
  ["Commit"
   ("c" "Commit staged" templedb-magit-commit)
   ("a" "Commit all (stage + commit)" templedb-magit-commit-all)])

(defun templedb-magit-commit ()
  "Commit staged changes."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (msg (read-string "Commit message: ")))
    (when (string-empty-p msg)
      (user-error "Commit message cannot be empty"))
    (templedb-magit--run-command "vcs" "commit" "-p" project "-m" msg)
    (message "Committed: %s" msg)
    (templedb-magit--auto-refresh)))

(defun templedb-magit-commit-all ()
  "Stage all and commit."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (msg (read-string "Commit message (all files): ")))
    (when (string-empty-p msg)
      (user-error "Commit message cannot be empty"))
    (templedb-magit--run-command "vcs" "add" "-p" project "--all")
    (templedb-magit--run-command "vcs" "commit" "-p" project "-m" msg)
    (message "Committed all: %s" msg)
    (templedb-magit--auto-refresh)))

;;; Log

(transient-define-prefix templedb-magit-log-transient ()
  "Show log."
  ["Log"
   ("l" "Log (current branch)" templedb-magit-log)
   ("a" "Log (all branches)" templedb-magit-log-all)])

(defun templedb-magit--display-log (output)
  "Display log OUTPUT in a navigable buffer."
  (let ((buf (get-buffer-create (format "*templedb-log: %s*" templedb-magit--current-project))))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (propertize (format "Commit log: %s\n\n" templedb-magit--current-project)
                            'face 'bold))
        (insert output)
        (goto-char (point-min))
        ;; Fontify hashes
        (while (re-search-forward "\\b\\([0-9a-fA-F]\\{8,\\}\\)\\b" nil t)
          (let ((hash (match-string 1)))
            (put-text-property (match-beginning 1) (match-end 1)
                               'face 'templedb-magit-hash)
            (put-text-property (match-beginning 1) (match-end 1)
                               'templedb-commit-hash hash)))
        (goto-char (point-min)))
      (setq buffer-read-only t)
      (setq templedb-magit--current-project
            (buffer-local-value 'templedb-magit--current-project
                                (get-buffer (format "*templedb-magit: %s*"
                                                    templedb-magit--current-project))))
      (local-set-key (kbd "RET") #'templedb-magit-show-commit-at-point)
      (local-set-key (kbd "q") #'quit-window))
    (display-buffer buf)))

(defun templedb-magit-log ()
  "Show commit log for current branch."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (output (templedb-magit--run-command "vcs" "log" project "-n" "30")))
    (templedb-magit--display-log output)))

(defun templedb-magit-log-all ()
  "Show commit log for all branches."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (output (templedb-magit--run-command "vcs" "log" project "-n" "50")))
    (templedb-magit--display-log output)))

(defun templedb-magit-show-commit-at-point ()
  "Show details for commit at point."
  (interactive)
  (if-let ((hash (get-text-property (point) 'templedb-commit-hash)))
      (let* ((project (templedb-magit--ensure-project))
             (output (templedb-magit--run-command "vcs" "show" project hash))
             (buf (get-buffer-create (format "*templedb-commit: %s*" (substring hash 0 8)))))
        (with-current-buffer buf
          (let ((inhibit-read-only t))
            (erase-buffer)
            (insert output))
          (setq buffer-read-only t)
          (goto-char (point-min))
          (local-set-key (kbd "q") #'quit-window))
        (display-buffer buf))
    (message "No commit hash at point")))

;;; Branch

(transient-define-prefix templedb-magit-branch-transient ()
  "Branch operations."
  ["Branch"
   ("b" "List branches" templedb-magit-branch-list)
   ("c" "Create branch" templedb-magit-branch-create)
   ("s" "Switch branch" templedb-magit-branch-switch)
   ("d" "Delete branch" templedb-magit-branch-delete)])

(defun templedb-magit-branch-list ()
  "List branches."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (output (templedb-magit--run-command "vcs" "branch" project)))
    (message "%s" (string-trim output))))

(defun templedb-magit-branch-create (name)
  "Create branch NAME."
  (interactive "sNew branch name: ")
  (let ((project (templedb-magit--ensure-project)))
    (templedb-magit--run-command "vcs" "branch" project name)
    (message "Created branch: %s" name)))

(defun templedb-magit-branch-switch (branch)
  "Switch to BRANCH."
  (interactive
   (list (read-string "Switch to branch: ")))
  (let ((project (templedb-magit--ensure-project)))
    (templedb-magit--run-command "vcs" "switch" project branch)
    (message "Switched to: %s" branch)
    (templedb-magit--auto-refresh)))

(defun templedb-magit-branch-delete (branch)
  "Delete BRANCH."
  (interactive
   (list (read-string "Delete branch: ")))
  (let ((project (templedb-magit--ensure-project)))
    (when (yes-or-no-p (format "Delete branch '%s'? " branch))
      (templedb-magit--run-command "vcs" "branch" project "-d" branch)
      (message "Deleted branch: %s" branch))))

;;; Merge

(transient-define-prefix templedb-magit-merge-transient ()
  "Merge operations."
  ["Merge"
   ("m" "Merge branch" templedb-magit-merge)
   ("s" "Squash merge" templedb-magit-merge-squash)])

(defun templedb-magit-merge (source)
  "Merge SOURCE branch into current."
  (interactive "sMerge from branch: ")
  (let ((project (templedb-magit--ensure-project)))
    (templedb-magit--run-command "vcs" "merge" project source)
    (message "Merged: %s" source)
    (templedb-magit--auto-refresh)))

(defun templedb-magit-merge-squash (source)
  "Squash merge SOURCE branch."
  (interactive "sSquash merge from branch: ")
  (let ((project (templedb-magit--ensure-project)))
    (templedb-magit--run-command "vcs" "merge" project source "--squash")
    (message "Squash merged: %s" source)
    (templedb-magit--auto-refresh)))

;;; Push / Publish

(transient-define-prefix templedb-magit-push-transient ()
  "Push/Publish operations."
  ["Publish"
   ("p" "Publish (commit + materialize + push)" templedb-magit-publish)
   ("f" "Force publish" templedb-magit-publish-force)]
  ["Export"
   ("e" "Export to git" templedb-magit-export)
   ("E" "Export + push" templedb-magit-export-push)])

(defun templedb-magit-publish ()
  "Publish project (commit + materialize + push to mirrors)."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (msg (read-string "Publish message: ")))
    (message "Publishing %s..." project)
    (let ((output (templedb-magit--run-command "publish" "run" project "-m" msg)))
      (message "Published: %s" (string-trim output))
      (templedb-magit--auto-refresh))))

(defun templedb-magit-publish-force ()
  "Force publish project."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (msg (read-string "Force publish message: ")))
    (when (yes-or-no-p "Force publish? This will force materialize. ")
      (message "Force publishing %s..." project)
      (let ((output (templedb-magit--run-command "publish" "run" project "-m" msg "-f")))
        (message "Published: %s" (string-trim output))
        (templedb-magit--auto-refresh)))))

(defun templedb-magit-export ()
  "Export database commits to git."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (output (templedb-magit--run-command "vcs" "export" project)))
    (message "Exported: %s" (string-trim output))))

(defun templedb-magit-export-push ()
  "Export database commits to git and push."
  (interactive)
  (let* ((project (templedb-magit--ensure-project))
         (output (templedb-magit--run-command "vcs" "export" project "--push")))
    (message "Exported+pushed: %s" (string-trim output))))

;;; CLI Command

(transient-define-prefix templedb-magit-run-transient ()
  "Run CLI commands."
  ["CLI"
   ("!" "Run templedb command" templedb-magit-run-command)
   ("s" "VCS status --refresh" templedb-magit-run-status)
   ("e" "Enter edit mode" templedb-magit-run-edit-mode)
   ("D" "Discard changes" templedb-magit-run-discard)])

(defun templedb-magit-run-command (cmd)
  "Run arbitrary templedb CMD."
  (interactive "stempledb ")
  (let* ((args (split-string cmd))
         (result (apply #'templedb-magit--run-command-no-error args))
         (exit-code (car result))
         (output (cdr result)))
    (if (zerop exit-code)
        (message "%s" (string-trim output))
      (message "Error (%d): %s" exit-code (string-trim output)))))

(defun templedb-magit-run-status ()
  "Run vcs status --refresh."
  (interactive)
  (templedb-magit-refresh))

(defun templedb-magit-run-edit-mode ()
  "Enter edit mode for project."
  (interactive)
  (let ((project (templedb-magit--ensure-project)))
    (templedb-magit--run-command "vcs" "edit" project)
    (message "Edit mode enabled for %s" project)))

(defun templedb-magit-run-discard ()
  "Discard all changes."
  (interactive)
  (let ((project (templedb-magit--ensure-project)))
    (when (yes-or-no-p (format "Discard ALL changes in %s? " project))
      (templedb-magit--run-command "vcs" "discard" project "-f")
      (message "Discarded changes")
      (templedb-magit--auto-refresh))))

;;; Mode Definition

(defvar templedb-magit-status-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'templedb-magit-edit-file)
    (define-key map (kbd "e") #'templedb-magit-edit-file)
    (define-key map (kbd "v") #'templedb-magit-show-file)
    (define-key map (kbd "s") #'templedb-magit-stage-file)
    (define-key map (kbd "S") #'templedb-magit-stage-all)
    (define-key map (kbd "u") #'templedb-magit-unstage-file)
    (define-key map (kbd "U") #'templedb-magit-unstage-all)
    (define-key map (kbd "c") #'templedb-magit-commit-transient)
    (define-key map (kbd "d") #'templedb-magit-diff)
    (define-key map (kbd "l") #'templedb-magit-log-transient)
    (define-key map (kbd "b") #'templedb-magit-branch-transient)
    (define-key map (kbd "P") #'templedb-magit-push-transient)
    (define-key map (kbd "m") #'templedb-magit-merge-transient)
    (define-key map (kbd "!") #'templedb-magit-run-transient)
    (define-key map (kbd "g") #'templedb-magit-refresh)
    (define-key map (kbd "TAB") #'templedb-magit--toggle-section-at-point)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap for TempleDB Magit status mode.")

(define-derived-mode templedb-magit-status-mode special-mode "TempleDB"
  "Major mode for TempleDB Magit status buffer.

\\{templedb-magit-status-mode-map}"
  (setq truncate-lines t)
  (setq buffer-read-only t))

;;; Entry Points

;;;###autoload
(defun templedb-magit-status ()
  "Show TempleDB status for current project (auto-detected)."
  (interactive)
  (if-let ((project (templedb-magit--detect-project)))
      (templedb-magit-status-project project)
    (call-interactively #'templedb-magit-status-project)))

;;;###autoload
(defun templedb-magit-status-project (project)
  "Show TempleDB status for PROJECT."
  (interactive
   (list (templedb-magit--read-project)))
  (let ((buf (get-buffer-create (format "*templedb-magit: %s*" project))))
    (with-current-buffer buf
      (templedb-magit-status-mode)
      (setq templedb-magit--current-project project)
      (templedb-magit-refresh))
    (switch-to-buffer buf)))

(provide 'templedb-magit)

;;; templedb-magit.el ends here
