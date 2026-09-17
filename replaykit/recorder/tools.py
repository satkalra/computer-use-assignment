_REF = {
    "type": "string",
    "description": "An element ref from the snapshot, e.g. 'e34'.",
}


TOOLS = [
    {
        "name": "click",
        "description": "Click the element with this ref.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": _REF},
            "required": ["ref"],
        },
    },
    {
        "name": "fill",
        "description": "Type text into the textbox with this ref.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": _REF, "value": {"type": "string"}},
            "required": ["ref", "value"],
        },
    },
    {
        "name": "select",
        "description": "Choose an option by visible text in the combobox with this ref.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": _REF, "value": {"type": "string"}},
            "required": ["ref", "value"],
        },
    },
    {
        "name": "goto",
        "description": "Navigate directly to a URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "extract",
        "description": "Capture this element's text as a named flow output.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": _REF, "output_name": {"type": "string"}},
            "required": ["ref", "output_name"],
        },
    },
    {
        "name": "done",
        "description": "Call once the goal is achieved and outputs are extracted.",
        "input_schema": {
            "type": "object",
            "properties": {"outputs": {"type": "object"}},
            "required": ["outputs"],
        },
    },
]
