;;; templedb-graph.el --- Graph exploration for TempleDB -*- lexical-binding: t; -*-

;; Copyright (C) 2026 TempleDB Contributors

;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1") (transient "0.3.0"))
;; Keywords: tools

;;; Commentary:

;; Dependency graph, cross-project analysis, and code search.
;; Equivalent to GUI /graph page.
;;
;; Entry points:
;;   M-x templedb-graph          - Main transient menu
;;   M-x templedb-graph-search   - Fuzzy search across everything
;;   M-x templedb-graph-who-uses - Find who uses a var/secret
;;   M-x templedb-graph-deps     - Show project dependencies

;;; Code:

(require 'transient)

(defcustom templedb-graph-executable "templedb"
  "Path to templedb."
  :type 'string
  :group 'tools)

;;; Utilities

(defun templedb-graph--run (&rest args)
  "Run templedb ARGS, return output."
  (with-temp-buffer
    (let ((exit-code (apply #'call-process templedb-graph-executable nil t nil args)))
      (if (zerop exit-code)
          (buffer-string)
        (error "templedb failed: %s" (buffer-string))))))

(defun templedb-graph--project-list ()
  "Get project slugs."
  (let ((output (templedb-graph--run "project" "list" "--format" "json")))
    (condition-case nil
        (mapcar (lambda (p) (alist-get 'slug p))
                (append (json-read-from-string output) nil))
      (error nil))))

(defun templedb-graph--read-project ()
  "Prompt for project."
  (completing-read "Project: " (templedb-graph--project-list) nil t))

;;; Results Buffer

(defvar templedb-graph-results-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'templedb-graph-open-at-point)
    (define-key map (kbd "n") #'templedb-graph-next-result)
    (define-key map (kbd "p") #'templedb-graph-prev-result)
    (define-key map (kbd "q") #'quit-window)
    map)
  "Keymap for graph results.")

(define-derived-mode templedb-graph-results-mode special-mode "TDB-Graph"
  "Mode for TempleDB graph results.

\\{templedb-graph-results-mode-map}"
  (setq truncate-lines t))

(defun templedb-graph--display-results (title output)
  "Display graph OUTPUT in navigable buffer with TITLE."
  (let ((buf (get-buffer-create (format "*templedb-graph: %s*" title))))
    (with-current-buffer buf
      (templedb-graph-results-mode)
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (propertize (format "%s\n" title) 'face 'bold))
        (insert (propertize "RET=open n=next p=prev q=quit\n\n" 'face 'shadow))
        ;; Parse and insert results, making file paths clickable
        (dolist (line (split-string output "\n" t))
          (let ((trimmed (string-trim line)))
            (cond
             ;; Match file paths like "project:path/to/file.py:42"
             ((string-match "^\\([^:]+\\):\\([^:]+\\):\\([0-9]+\\)" trimmed)
              (let ((proj (match-string 1 trimmed))
                    (file (match-string 2 trimmed))
                    (line-num (match-string 3 trimmed)))
                (insert (propertize trimmed
                                    'face 'link
                                    'templedb-graph-project proj
                                    'templedb-graph-file file
                                    'templedb-graph-line (string-to-number line-num))
                        "\n")))
             ;; Match bare file paths "path/to/file.py"
             ((string-match "^\\s*\\([^ ]+\\.[a-z]+\\)" trimmed)
              (insert (propertize trimmed
                                  'face 'link
                                  'templedb-graph-file (match-string 1 trimmed))
                      "\n"))
             (t (insert trimmed "\n"))))))
      (goto-char (point-min)))
    (display-buffer buf)))

(defun templedb-graph-open-at-point ()
  "Open file at point."
  (interactive)
  (let ((file (get-text-property (point) 'templedb-graph-file))
        (project (get-text-property (point) 'templedb-graph-project))
        (line-num (get-text-property (point) 'templedb-graph-line)))
    (cond
     ((and file project)
      ;; Try to resolve full path
      (let* ((output (templedb-graph--run "project" "list" "--format" "json"))
             (projects (condition-case nil (append (json-read-from-string output) nil) (error nil)))
             (proj-data (seq-find (lambda (p) (string= (alist-get 'slug p) project)) projects))
             (repo-url (when proj-data (alist-get 'repo_url proj-data)))
             (base (when repo-url (replace-regexp-in-string "^file://" "" repo-url)))
             (full-path (when base (expand-file-name file base))))
        (if (and full-path (file-exists-p full-path))
            (progn
              (find-file full-path)
              (when line-num (goto-char (point-min)) (forward-line (1- line-num))))
          (message "Cannot resolve path: %s:%s" project file))))
     (file
      (if (file-exists-p file)
          (find-file file)
        (message "File not found: %s" file)))
     (t (message "No file at point")))))

(defun templedb-graph-next-result ()
  "Move to next result line."
  (interactive)
  (forward-line 1)
  (while (and (not (eobp))
              (not (get-text-property (point) 'templedb-graph-file)))
    (forward-line 1)))

(defun templedb-graph-prev-result ()
  "Move to previous result line."
  (interactive)
  (forward-line -1)
  (while (and (not (bobp))
              (not (get-text-property (point) 'templedb-graph-file)))
    (forward-line -1)))

;;; Search

;;;###autoload
(defun templedb-graph-search (query)
  "Fuzzy search across everything for QUERY."
  (interactive "sSearch: ")
  (let ((output (templedb-graph--run "graph" "search" query)))
    (templedb-graph--display-results (format "Search: %s" query) output)))

;;;###autoload
(defun templedb-graph-who-uses (name)
  "Find which projects use NAME (secret/var/string)."
  (interactive "sWho uses: ")
  (let ((output (templedb-graph--run "graph" "who-uses" name)))
    (templedb-graph--display-results (format "Who uses: %s" name) output)))

;;;###autoload
(defun templedb-graph-deps (project)
  "Show dependency graph for PROJECT."
  (interactive (list (templedb-graph--read-project)))
  (let ((output (templedb-graph--run "graph" "deps" project)))
    (templedb-graph--display-results (format "Deps: %s" project) output)))

(defun templedb-graph-build-deps (project)
  "Show build dependency graph for PROJECT."
  (interactive (list (templedb-graph--read-project)))
  (let ((output (templedb-graph--run "graph" "build-deps" project)))
    (templedb-graph--display-results (format "Build deps: %s" project) output)))

(defun templedb-graph-importers (project file)
  "Show what imports FILE in PROJECT."
  (interactive
   (list (templedb-graph--read-project)
         (read-string "File path: ")))
  (let ((output (templedb-graph--run "graph" "importers" project file)))
    (templedb-graph--display-results (format "Importers: %s" file) output)))

(defun templedb-graph-callers (project symbol)
  "Show what calls SYMBOL in PROJECT."
  (interactive
   (list (templedb-graph--read-project)
         (read-string "Symbol: ")))
  (let ((output (templedb-graph--run "graph" "callers" project symbol)))
    (templedb-graph--display-results (format "Callers: %s" symbol) output)))

(defun templedb-graph-changes (project)
  "Show what changed since last deploy for PROJECT."
  (interactive (list (templedb-graph--read-project)))
  (let ((output (templedb-graph--run "graph" "changes" project)))
    (templedb-graph--display-results (format "Changes: %s" project) output)))

(defun templedb-graph-overview ()
  "Cross-project analysis overview."
  (interactive)
  (let ((output (templedb-graph--run "graph" "overview")))
    (templedb-graph--display-results "Overview" output)))

;;; Main Transient

;;;###autoload
(transient-define-prefix templedb-graph ()
  "TempleDB graph exploration."
  ["Search"
   ("s" "Fuzzy search" templedb-graph-search)
   ("w" "Who uses" templedb-graph-who-uses)
   ("o" "Overview" templedb-graph-overview)]
  ["Dependencies"
   ("d" "Project deps" templedb-graph-deps)
   ("b" "Build deps" templedb-graph-build-deps)
   ("c" "Changes since deploy" templedb-graph-changes)]
  ["Code Analysis"
   ("i" "Importers" templedb-graph-importers)
   ("C" "Callers" templedb-graph-callers)])

(provide 'templedb-graph)

;;; templedb-graph.el ends here
