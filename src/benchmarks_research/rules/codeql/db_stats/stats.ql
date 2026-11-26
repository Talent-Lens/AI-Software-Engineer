import python

select
  count(File f | f.fromSource() and f.getExtension() = "py" | f) as py_files,
  count(Function f | f.getLocation().getFile().fromSource() | f) as py_functions
