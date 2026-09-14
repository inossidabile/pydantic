use pyo3::prelude::*;
use pyo3::{PyTraverseError, PyVisit};
use smallvec::SmallVec;

use crate::build_tools::py_schema_err;
use crate::lookup_key::{LookupPath, PathItem, ValidationAlias};
use crate::py_gc::PyGcTraverse;

#[derive(Debug)]
pub enum Discriminator {
    /// use `LookupPaths` to find the tag, same as we do to find values in typed_dict aliases
    LookupPaths(SmallVec<[LookupPath; 1]>),
    /// call a function to find the tag to use
    Function(Py<PyAny>),
}

impl Discriminator {
    pub fn new(raw: &Bound<'_, PyAny>) -> PyResult<Self> {
        if raw.is_callable() {
            return Ok(Self::Function(raw.clone().unbind()));
        }

        let lookup: ValidationAlias = raw.extract()?;
        let paths = lookup.into_paths();

        // a discriminator must resolve to a single tag value to look up the matching union member,
        // whereas a `...` wildcard resolves to a list, so it never makes sense here (unlike in a
        // field's `validation_alias`, where the resulting list is exactly what's wanted)
        if paths
            .iter()
            .any(|path| path.rest().iter().any(|item| matches!(item, PathItem::Wildcard)))
        {
            return py_schema_err!("Discriminator paths cannot contain a '...' wildcard item");
        }

        Ok(Self::LookupPaths(paths))
    }

    pub fn to_string_py(&self, py: Python) -> PyResult<String> {
        match self {
            Self::Function(f) => Ok(format!("{}()", f.getattr(py, "__name__")?)),
            Self::LookupPaths(paths) => Ok(paths.iter().map(ToString::to_string).collect::<Vec<_>>().join(" | ")),
        }
    }
}

impl PyGcTraverse for Discriminator {
    fn py_gc_traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        match self {
            Self::Function(obj) => visit.call(obj)?,
            Self::LookupPaths(_) => {}
        }
        Ok(())
    }
}

pub(crate) const SMALL_UNION_THRESHOLD: usize = 4;
