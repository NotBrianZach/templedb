-- Seed binary-asset file_types so the scanner can register SVG/PNG/font/PDF/etc.
-- Without these rows, the importer silently drops any file whose type isn't already
-- in file_types (see importer/__init__.py:_import_file_metadata line 137).

INSERT OR IGNORE INTO file_types (type_name, category, description) VALUES
  ('image_svg',    'asset', 'SVG vector image'),
  ('image_png',    'asset', 'PNG raster image'),
  ('image_jpg',    'asset', 'JPEG raster image'),
  ('image_gif',    'asset', 'GIF image'),
  ('image_webp',   'asset', 'WebP image'),
  ('image_ico',    'asset', 'Icon image'),
  ('font',         'asset', 'Font file (woff/woff2/ttf/otf/eot)'),
  ('pdf',          'asset', 'PDF document'),
  ('wasm',         'asset', 'WebAssembly binary'),
  ('audio',        'asset', 'Audio file'),
  ('video',        'asset', 'Video file'),
  ('archive',      'asset', 'Compressed archive'),
  ('binary_asset', 'asset', 'Generic binary asset');
