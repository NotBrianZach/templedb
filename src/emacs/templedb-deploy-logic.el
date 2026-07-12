;;; templedb-deploy-logic.el --- Prolog deployment logic for TempleDB -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Zach
;; Version: 0.2.0
;; Package-Requires: ((emacs "28.1"))
;; Keywords: tools, deployment

;;; Commentary:

;; Emacs interface for TempleDB's Prolog-based deployment logic.
;; All queries run as single swipl invocations — Prolog does the
;; reasoning, JSON serialization, topo sort, and parallel grouping.
;;
;;   M-x templedb-deploy-validate  ; Validate a project
;;   M-x templedb-deploy-graph     ; Show dependency graph
;;   M-x templedb-deploy-order     ; Show deploy order + parallel phases
;;   M-x templedb-prolog-query     ; Interactive Prolog query

;;; Code:

(require 'json)

(defgroup templedb-deploy nil
  "Prolog-based deployment logic for TempleDB."
  :group 'tools
  :prefix "templedb-deploy-")

(defcustom templedb-deploy-swipl nil
  "Path to swipl. If nil, searches PATH then nix store."
  :type '(choice (const nil) string)
  :group 'templedb-deploy)

(defcustom templedb-deploy-pl-file
  (expand-file-name "~/templeDB/src/services/deploy_logic.pl")
  "Path to deploy_logic.pl."
  :type 'file
  :group 'templedb-deploy)

;;; Faces

(defface templedb-deploy-ok '((t :foreground "#4a9a6a" :weight bold)) "Valid.")
(defface templedb-deploy-fail '((t :foreground "#e94560" :weight bold)) "Failed.")
(defface templedb-deploy-project '((t :foreground "#4a9eff" :weight bold)) "Project.")
(defface templedb-deploy-dep '((t :foreground "#808098")) "Muted.")
(defface templedb-deploy-phase '((t :foreground "#c8a040" :weight bold)) "Phase.")
(defface templedb-deploy-arrow '((t :foreground "#4a9eff")) "Arrow.")
(defface templedb-deploy-heading '((t :foreground "#e94560" :weight bold :height 1.1)) "Heading.")

;;; Core: single swipl calls

(defun templedb-deploy--find-swipl ()
  "Find swipl binary."
  (or templedb-deploy-swipl
      (executable-find "swipl")
      (car (last (file-expand-wildcards "/nix/store/*-swi-prolog-*/bin/swipl")))
      (error "swipl not found")))

(defun templedb-deploy--run-goal (goal)
  "Run Prolog GOAL via swipl, return stdout string."
  (with-temp-buffer
    (call-process (templedb-deploy--find-swipl) nil t nil
                  "-q" "-l" templedb-deploy-pl-file
                  "-g" goal "-g" "halt")
    (buffer-string)))

(defun templedb-deploy--run-json (goal)
  "Run GOAL that outputs JSON, parse it."
  (let ((output (string-trim (templedb-deploy--run-goal goal))))
    (when (and output (not (string-empty-p output)))
      (json-read-from-string output))))

(defun templedb-deploy--batch ()
  "Run batch_json: all projects, order, groups in one swipl call."
  (templedb-deploy--run-json "batch_json"))

;;; Commands

;;;###autoload
(defun templedb-deploy-validate (project)
  "Validate deployment readiness for PROJECT (single swipl call)."
  (interactive
   (let* ((batch (templedb-deploy--batch))
          (slugs (mapcar (lambda (p) (replace-regexp-in-string "_" "-" (cdr (assq 'slug p))))
                         (cdr (assq 'projects batch)))))
     (list (completing-read "Project: " slugs))))
  (let* ((slug (replace-regexp-in-string "-" "_" project))
         (result (templedb-deploy--run-json (format "validate_json(%s)" slug)))
         (buf (get-buffer-create "*templedb-deploy-validate*")))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (templedb-deploy-mode)
        (insert (propertize "Deployment Validation\n" 'face 'templedb-deploy-heading)
                (propertize (make-string 21 ?=) 'face 'templedb-deploy-dep) "\n\n")
        (let-alist result
          (dolist (pair `(("Project:    " ,project templedb-deploy-project)
                          ("Type:       " ,(symbol-name .type) templedb-deploy-dep)
                          ("Valid:      " ,(if (eq .valid t) "yes" "no") ,(if (eq .valid t) 'templedb-deploy-ok 'templedb-deploy-fail))
                          ("Can Deploy: " ,(if .can_deploy "yes" "no") ,(if .can_deploy 'templedb-deploy-ok 'templedb-deploy-fail))
                          ("Has Cycle:  " ,(if .has_cycle "CYCLE" "no") ,(if .has_cycle 'templedb-deploy-fail 'templedb-deploy-ok))))
            (insert (propertize (concat "  " (nth 0 pair)) 'face 'templedb-deploy-dep)
                    (propertize (nth 1 pair) 'face (nth 2 pair)) "\n"))
          (insert (propertize "\n  Dependencies\n" 'face 'templedb-deploy-heading))
          (if (> (length .deps) 0)
              (seq-doseq (dep .deps)
                (insert (propertize "    -> " 'face 'templedb-deploy-arrow)
                        (propertize (format "%s\n" dep) 'face 'templedb-deploy-project)))
            (insert (propertize "    (none)\n" 'face 'templedb-deploy-dep)))
          (insert (propertize "\n  Deploy Targets\n" 'face 'templedb-deploy-heading))
          (if (> (length .targets) 0)
              (seq-doseq (tgt .targets)
                (insert (propertize "    * " 'face 'templedb-deploy-phase)
                        (propertize (format "%s\n" tgt) 'face 'templedb-deploy-project)))
            (insert (propertize "    (none)\n" 'face 'templedb-deploy-dep)))
          (when (> (length .required_env) 0)
            (insert (propertize "\n  Required Env Vars\n" 'face 'templedb-deploy-heading))
            (seq-doseq (var .required_env)
              (insert "    $ " (propertize (format "%s\n" var) 'face 'font-lock-variable-name-face))))
          (when (> (length .health_checks) 0)
            (insert (propertize "\n  Health Checks\n" 'face 'templedb-deploy-heading))
            (seq-doseq (hc .health_checks)
              (let-alist hc
                (insert (propertize "    # " 'face 'templedb-deploy-ok)
                        (format "%s (expect %s)\n" .url .status))))))))
    (pop-to-buffer buf)
    (goto-char (point-min))))

;;;###autoload
(defun templedb-deploy-order ()
  "Show deployment order with parallel phases (single swipl call)."
  (interactive)
  (let* ((batch (templedb-deploy--batch))
         (buf (get-buffer-create "*templedb-deploy-order*")))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (templedb-deploy-mode)
        (insert (propertize "Deployment Order\n" 'face 'templedb-deploy-heading)
                (propertize (make-string 16 ?=) 'face 'templedb-deploy-dep) "\n\n")
        (let ((phase 1))
          (seq-doseq (group (cdr (assq 'parallel_groups batch)))
            (insert (propertize (format "  Phase %d  > " phase) 'face 'templedb-deploy-phase))
            (seq-doseq (p group)
              (insert (propertize (format " %s " (replace-regexp-in-string "_" "-" (symbol-name p)))
                                  'face 'templedb-deploy-project)))
            (insert "\n")
            (setq phase (1+ phase))))
        (insert (propertize "\n  Sequential\n" 'face 'templedb-deploy-heading))
        (let ((idx 1))
          (seq-doseq (p (cdr (assq 'deploy_order batch)))
            (insert (propertize (format "  %2d. " idx) 'face 'templedb-deploy-dep)
                    (propertize (format "%s\n" (replace-regexp-in-string "_" "-" (symbol-name p)))
                                'face 'templedb-deploy-project))
            (setq idx (1+ idx))))))
    (pop-to-buffer buf)
    (goto-char (point-min))))

;;;###autoload
(defun templedb-deploy-graph ()
  "Show dependency graph (single swipl call)."
  (interactive)
  (let* ((batch (templedb-deploy--batch))
         (projects (cdr (assq 'projects batch)))
         (buf (get-buffer-create "*templedb-deploy-graph*")))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (templedb-deploy-mode)
        (insert (propertize "Dependency Graph\n" 'face 'templedb-deploy-heading)
                (propertize (make-string 16 ?=) 'face 'templedb-deploy-dep) "\n\n")
        (insert (propertize "  Edges\n" 'face 'templedb-deploy-heading))
        (let ((has-edges nil))
          (seq-doseq (project projects)
            (let-alist project
              (seq-doseq (dep .deps)
                (setq has-edges t)
                (insert "    "
                        (propertize (replace-regexp-in-string "_" "-" (symbol-name dep))
                                    'face 'templedb-deploy-project)
                        (propertize " -> " 'face 'templedb-deploy-arrow)
                        (propertize (format "%s\n" (replace-regexp-in-string "_" "-" (symbol-name .slug)))
                                    'face 'templedb-deploy-project)))))
          (unless has-edges
            (insert (propertize "    (none)\n" 'face 'templedb-deploy-dep))))
        (insert (propertize "\n  Projects\n" 'face 'templedb-deploy-heading))
        (seq-doseq (project projects)
          (let-alist project
            (let ((name (replace-regexp-in-string "_" "-" (symbol-name .slug))))
              (insert "    "
                      (propertize (format "%-25s" name) 'face 'templedb-deploy-project)
                      (propertize (format "[%s]" .type) 'face 'templedb-deploy-dep))
              (when (> (length .targets) 0)
                (insert (propertize " -> " 'face 'templedb-deploy-arrow))
                (seq-doseq (tgt .targets)
                  (insert (propertize (format "%s " tgt) 'face 'templedb-deploy-phase))))
              (insert "\n"))))))
    (pop-to-buffer buf)
    (goto-char (point-min))))

;;;###autoload
(defun templedb-prolog-query (query-str)
  "Run Prolog QUERY-STR directly against swipl."
  (interactive "sProlog query: ")
  (let* ((output (templedb-deploy--run-goal
                  (format "forall((%s), (write(yes), nl)) ; write(no)"
                          query-str)))
         (buf (get-buffer-create "*templedb-prolog*")))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (goto-char (point-max))
        (unless (= (point-min) (point-max)) (insert "\n"))
        (insert (propertize (format "?- %s.\n" query-str) 'face 'templedb-deploy-heading)
                (string-trim output) "\n")))
    (pop-to-buffer buf)
    (goto-char (point-max))))

;;; Mode

(defvar templedb-deploy-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map "q" #'quit-window)
    (define-key map "g" #'templedb-deploy-order)
    (define-key map "v" #'templedb-deploy-validate)
    (define-key map "G" #'templedb-deploy-graph)
    (define-key map "?" #'templedb-prolog-query)
    map))

(define-derived-mode templedb-deploy-mode special-mode "TempleDB-Deploy"
  "Major mode for TempleDB deployment logic views.
\\{templedb-deploy-mode-map}")

(provide 'templedb-deploy-logic)
;;; templedb-deploy-logic.el ends here
