// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

//! cel-core for Python: check a rule to a CheckedExpr, and evaluate a CheckedExpr on proto activations.
//!
//! The environment is the same env YAML plus FileDescriptorSet the other engines read, through the
//! adapter in ../rust/src/lib.rs. A CheckedExpr travels as a google.protobuf.Any, as cel-cpp writes it.

use cel_core::{Ast, MapActivation, Value};
use cel_core_proto::{AstToProto, CheckedExpr, ParsedExpr, ProstMessage, check_result_from_proto, from_parsed_expr};
use cel_neutral_rs::{EnvConfig, env_from_config};
use prost::Message;
use prost_reflect::{DescriptorPool, DynamicMessage};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};

const CHECKED_EXPR_URL: &str = "type.googleapis.com/cel.expr.CheckedExpr";

fn value_error(e: impl ToString) -> PyErr {
    PyValueError::new_err(e.to_string())
}

#[pyclass(unsendable)]
struct Env {
    env: cel_core::Env,
    pool: DescriptorPool,
    types: Vec<(String, String)>,
}

#[pymethods]
impl Env {
    #[new]
    fn new(env_yaml: &str, descriptor_set: &[u8]) -> PyResult<Self> {
        let config: EnvConfig = serde_yaml::from_str(env_yaml).map_err(value_error)?;
        let env = env_from_config(&config, descriptor_set).map_err(value_error)?;
        let pool = DescriptorPool::decode(descriptor_set).map_err(value_error)?;
        let types = config.variables.iter().map(|v| (v.name.clone(), v.type_name.clone())).collect();
        Ok(Self { env, pool, types })
    }

    /// Parse and type-check `expr`; return the CheckedExpr wrapped in an Any, or raise ValueError.
    fn check<'py>(&self, py: Python<'py>, expr: &str) -> PyResult<Bound<'py, PyBytes>> {
        let ast = self.env.compile(expr).map_err(value_error)?;
        let checked = ast.to_checked_expr().map_err(value_error)?;
        let any = prost_types::Any { type_url: CHECKED_EXPR_URL.into(), value: checked.encode_to_vec() };
        Ok(PyBytes::new(py, &any.encode_to_vec()))
    }

    /// Evaluate a CheckedExpr (any engine's) on an activation of serialised proto messages, one per variable.
    fn eval<'py>(&self, py: Python<'py>, checked: &[u8], activation: Bound<'py, PyDict>) -> PyResult<Bound<'py, PyAny>> {
        let any = prost_types::Any::decode(checked).map_err(value_error)?;
        let checked = CheckedExpr::decode(any.value.as_slice()).map_err(value_error)?;
        let parsed = ParsedExpr { expr: checked.expr.clone(), source_info: checked.source_info.clone() };
        let expr = from_parsed_expr(&parsed).map_err(value_error)?;
        let ast = Ast::new_checked(expr, "", check_result_from_proto(&checked).map_err(value_error)?);
        let mut act = MapActivation::new();
        for (name, type_name) in &self.types {
            let Some(item) = activation.get_item(name)? else { continue };
            let desc = self.pool.get_message_by_name(type_name).ok_or_else(|| value_error(type_name))?;
            let msg = DynamicMessage::decode(desc, item.extract::<&[u8]>()?).map_err(value_error)?;
            act.insert(name.clone(), Value::Message(Box::new(ProstMessage::new(msg))));
        }
        let program = self.env.program(&ast).map_err(value_error)?;
        to_python(py, &program.eval(&act))
    }
}

fn to_python<'py>(py: Python<'py>, v: &Value) -> PyResult<Bound<'py, PyAny>> {
    Ok(match v {
        Value::Null => py.None().into_bound(py),
        Value::Bool(b) => b.into_pyobject(py)?.to_owned().into_any(),
        Value::Int(i) => i.into_pyobject(py)?.into_any(),
        Value::UInt(u) => u.into_pyobject(py)?.into_any(),
        Value::Double(d) => d.into_pyobject(py)?.into_any(),
        Value::String(s) => s.as_ref().into_pyobject(py)?.into_any(),
        Value::Bytes(b) => PyBytes::new(py, b).into_any(),
        Value::List(items) => {
            PyList::new(py, items.iter().map(|i| to_python(py, i)).collect::<PyResult<Vec<_>>>()?)?.into_any()
        }
        Value::Error(e) => return Err(value_error(e)),
        other => return Err(PyTypeError::new_err(format!("no Python form for {other:?}"))),
    })
}

#[pymodule]
fn cel_core_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Env>()?;
    Ok(())
}
