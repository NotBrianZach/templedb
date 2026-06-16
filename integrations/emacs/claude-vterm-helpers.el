;;; claude-vterm-helpers.el --- Helpers for Claude CLI in vterm -*- lexical-binding: t; -*-

;; Copyright (C) 2026 TempleDB Contributors

;; Author: TempleDB Contributors
;; URL: https://github.com/yourusername/templedb
;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1") (vterm "0.0.1"))
;; Keywords: tools, ai, terminal

;; This file is not part of GNU Emacs.

;;; Commentary:

;; Helpers for managing Claude CLI interactions in Emacs vterm.
;; Addresses the scrolling issue when pasting content into long conversations.
;;
;; Problem: When you paste content into Claude CLI in a vterm buffer with
;; long conversation history, it scrolls through the entire history before
;; processing your input.
;;
;; Solutions provided:
;;
;; 1. `claude-vterm-send-input` - Send input without triggering full repaint
;; 2. `claude-vterm-paste-and-send` - Paste from clipboard and send smartly
;; 3. `claude-vterm-clear-scrollback` - Clear scrollback before input
;; 4. `claude-vterm-mode` - Minor mode with helpful keybindings
;;
;; Usage:
;;   (require 'claude-vterm-helpers)
;;   (add-hook 'vterm-mode-hook #'claude-vterm-mode)
;;
;; Then in your Claude CLI vterm buffer:
;;   C-c C-v   - Paste and send (no scroll)
;;   C-c C-l   - Clear scrollback before sending
;;   C-c C-s   - Send current region/line smartly

;;; Code:

(require 'vterm)

(defgroup claude-vterm nil
  "Helpers for Claude CLI in vterm."
  :group 'vterm
  :prefix "claude-vterm-")

(defcustom claude-vterm-clear-scrollback-before-paste t
  "Clear vterm scrollback before pasting to prevent scroll."
  :type 'boolean
  :group 'claude-vterm)

(defcustom claude-vterm-max-scrollback 1000
  "Maximum scrollback lines to keep in Claude vterm buffers."
  :type 'integer
  :group 'claude-vterm)

(defcustom claude-vterm-inhibit-repaint-on-send nil
  "Inhibit terminal repaint when sending input (experimental).
This can prevent the scrolling behavior but may cause display issues."
  :type 'boolean
  :group 'claude-vterm)

;;; Core Functions

(defun claude-vterm-send-input (&optional clear-scrollback)
  "Send input to Claude CLI without triggering full conversation scroll.
If CLEAR-SCROLLBACK is non-nil, clear scrollback before sending."
  (interactive "P")
  (when (and clear-scrollback
             (derived-mode-p 'vterm-mode))
    (claude-vterm-clear-scrollback))

  ;; Use vterm's send function
  (vterm-send-return))

(defun claude-vterm-paste-and-send (&optional arg)
  "Paste from clipboard and send to Claude CLI without scroll.
With prefix ARG, don't clear scrollback first."
  (interactive "P")

  (when (derived-mode-p 'vterm-mode)
    ;; Clear scrollback unless prefix arg given
    (when (and claude-vterm-clear-scrollback-before-paste
               (not arg))
      (claude-vterm-clear-scrollback))

    ;; Paste content
    (let ((text (or (gui-get-selection 'CLIPBOARD)
                    (current-kill 0))))
      (when text
        ;; Send text character by character to avoid paste bracket issues
        (vterm-send-string text)
        ;; Send return
        (vterm-send-return)

        (message "Sent %d characters to Claude" (length text))))))

(defun claude-vterm-clear-scrollback ()
  "Clear vterm scrollback buffer to prevent scroll on next input."
  (interactive)
  (when (derived-mode-p 'vterm-mode)
    ;; Send clear sequence to terminal
    (vterm-send-string "clear")
    (vterm-send-return)

    ;; Also clear Emacs-side scrollback
    (vterm-clear-scrollback)

    (message "Cleared Claude vterm scrollback")))

(defun claude-vterm-send-region (start end)
  "Send region between START and END to Claude CLI smartly."
  (interactive "r")
  (when (derived-mode-p 'vterm-mode)
    (let ((text (buffer-substring-no-properties start end)))
      ;; Clear scrollback first
      (when claude-vterm-clear-scrollback-before-paste
        (claude-vterm-clear-scrollback)
        ;; Wait for clear to complete
        (sit-for 0.1))

      ;; Send text
      (vterm-send-string text)
      (vterm-send-return)

      (message "Sent region (%d chars) to Claude" (length text)))))

(defun claude-vterm-smart-send ()
  "Send current line or region to Claude CLI intelligently.
If region is active, send region. Otherwise send current line."
  (interactive)
  (cond
   ((use-region-p)
    (claude-vterm-send-region (region-beginning) (region-end))
    (deactivate-mark))
   (t
    (claude-vterm-send-input))))

;;; Scrollback Management

(defun claude-vterm-limit-scrollback ()
  "Limit scrollback buffer size to prevent performance issues."
  (when (derived-mode-p 'vterm-mode)
    (let ((lines (count-lines (point-min) (point-max))))
      (when (> lines claude-vterm-max-scrollback)
        (save-excursion
          (goto-char (point-min))
          (let ((delete-end (progn
                             (forward-line (- lines claude-vterm-max-scrollback))
                             (point))))
            ;; Delete old lines
            (delete-region (point-min) delete-end)))))))

(defun claude-vterm-auto-limit-scrollback ()
  "Automatically limit scrollback periodically."
  (when (derived-mode-p 'vterm-mode)
    (run-with-idle-timer 60 t #'claude-vterm-limit-scrollback)))

;;; Vterm Configuration Helpers

(defun claude-vterm-configure-for-claude ()
  "Configure current vterm buffer optimally for Claude CLI.
Reduces scrollback, disables unnecessary features."
  (interactive)
  (when (derived-mode-p 'vterm-mode)
    ;; Set local scrollback limit
    (setq-local vterm-max-scrollback claude-vterm-max-scrollback)

    ;; Disable line wrapping for better performance
    (setq-local truncate-lines t)

    ;; Enable auto-scrollback limiting
    (claude-vterm-auto-limit-scrollback)

    (message "Configured vterm for Claude CLI")))

;;; Alternative Screen Buffer Management

(defun claude-vterm-use-alternate-screen ()
  "Switch to alternate screen buffer (like vim/less).
This can prevent conversation history from scrolling."
  (interactive)
  (when (derived-mode-p 'vterm-mode)
    ;; Send ANSI escape sequence for alternate screen
    (vterm-send-string "\e[?1049h")
    (message "Switched to alternate screen")))

(defun claude-vterm-restore-main-screen ()
  "Restore main screen buffer."
  (interactive)
  (when (derived-mode-p 'vterm-mode)
    ;; Send ANSI escape sequence to restore main screen
    (vterm-send-string "\e[?1049l")
    (message "Restored main screen")))

;;; Keybindings and Minor Mode

(defvar claude-vterm-mode-map
  (let ((map (make-sparse-keymap)))
    ;; Smart paste and send
    (define-key map (kbd "C-c C-v") #'claude-vterm-paste-and-send)
    ;; Clear and send
    (define-key map (kbd "C-c C-l") #'claude-vterm-clear-scrollback)
    ;; Smart send (region or line)
    (define-key map (kbd "C-c C-s") #'claude-vterm-smart-send)
    ;; Configure for Claude
    (define-key map (kbd "C-c C-c") #'claude-vterm-configure-for-claude)
    ;; Alternate screen
    (define-key map (kbd "C-c C-a") #'claude-vterm-use-alternate-screen)
    map)
  "Keymap for `claude-vterm-mode'.")

;;;###autoload
(define-minor-mode claude-vterm-mode
  "Minor mode for improved Claude CLI experience in vterm.

Provides keybindings to manage conversation scrollback and input:

\\{claude-vterm-mode-map}"
  :init-value nil
  :lighter " Claude"
  :keymap claude-vterm-mode-map
  :group 'claude-vterm

  (when claude-vterm-mode
    ;; Auto-configure when mode is enabled
    (claude-vterm-configure-for-claude)))

;;; Auto-detection

(defun claude-vterm-detect-claude-cli ()
  "Detect if current vterm buffer is running Claude CLI.
Returns non-nil if Claude CLI is detected."
  (and (derived-mode-p 'vterm-mode)
       (save-excursion
         (goto-char (point-min))
         (or (re-search-forward "claude" nil t)
             (re-search-forward "anthropic" nil t)))))

;;;###autoload
(defun claude-vterm-maybe-enable ()
  "Enable `claude-vterm-mode' if Claude CLI is detected."
  (when (claude-vterm-detect-claude-cli)
    (claude-vterm-mode 1)))

;;; Setup Function

;;;###autoload
(defun claude-vterm-setup ()
  "Setup Claude vterm helpers globally.
Add this to your init.el:
  (with-eval-after-load 'vterm
    (require 'claude-vterm-helpers)
    (claude-vterm-setup))"
  (interactive)

  ;; Add hook to auto-detect Claude CLI
  (add-hook 'vterm-mode-hook #'claude-vterm-maybe-enable)

  (message "Claude vterm helpers installed! Use C-c C-v to paste without scroll"))

(provide 'claude-vterm-helpers)

;;; claude-vterm-helpers.el ends here
