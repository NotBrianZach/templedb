# GUI Page Modules

These files were mechanically extracted from gui.py.
They serve as a reference for incremental migration.

To activate a module:
1. Fix imports (gui_helpers → inline)
2. Delete the corresponding routes from gui.py
3. Add router import + include_router in gui.py
