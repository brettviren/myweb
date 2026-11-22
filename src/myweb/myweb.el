;;; myweb.el --- ox-hugo export for myweb page bundles  -*- lexical-binding: t -*-

;; Used by "myweb export" in batch and may be loaded in an interactive
;; Emacs so that saving with `org-hugo-auto-export-mode' gives the same
;; result.

;; A myweb item is a Hugo leaf bundle holding <slug>.org which exports
;; to index.md in the same directory, next to its images and files.

;;; Code:

(require 'ox-hugo)

(defun myweb--bundle-relative (orig path info)
  "Call ORIG with PATH and INFO, keeping links to bundle files relative.
ox-hugo returns \"/file.svg\" for a file that is already in the bundle
directory, which is wrong when the org source itself lives in the bundle."
  (let ((ret (funcall orig path info)))
    (if (and (plist-get info :hugo-bundle)
             (stringp ret)
             (string-prefix-p "/" ret)
             (file-exists-p (expand-file-name (substring ret 1)
                                              (org-hugo--get-pub-dir info))))
        (substring ret 1)
      ret)))

(advice-add 'org-hugo--attachment-rewrite-maybe :around #'myweb--bundle-relative)

(defun myweb-export-file (file)
  "Export org FILE with ox-hugo, never evaluating source blocks."
  (let ((org-export-use-babel nil)
        (org-hugo-auto-set-lastmod nil)
        (make-backup-files nil))
    (with-current-buffer (find-file-noselect file)
      (unwind-protect
          (org-hugo-export-to-md)
        (kill-buffer)))))

(defun myweb-export-batch ()
  "Export each file named on the command line."
  (let ((failed 0))
    (dolist (file command-line-args-left)
      (condition-case err
          (progn (myweb-export-file file)
                 (message "myweb: exported %s" file))
        (error (setq failed (1+ failed))
               (message "myweb: FAILED %s: %s" file (error-message-string err)))))
    (setq command-line-args-left nil)
    (kill-emacs (if (zerop failed) 0 1))))

(provide 'myweb)
;;; myweb.el ends here
