// Minimal JSON-schema subset validator: type, enum, properties, additionalProperties.
export function validate(schema, value) {
  if (!schema) return true;
  const t = Array.isArray(value) ? 'array' : value === null ? 'null' : typeof value;
  if (schema.type && schema.type !== t) return false;
  if (schema.enum && !schema.enum.includes(value)) return false;
  if (schema.type === 'object') {
    const props = schema.properties ?? {};
    for (const [k, v] of Object.entries(value)) {
      if (!(k in props)) { if (schema.additionalProperties === false) return false; continue; }
      if (!validate(props[k], v)) return false;
    }
    for (const k of schema.required ?? []) if (!(k in value)) return false;
  }
  return true;
}
