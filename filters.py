import json

def register_filters(app):
    @app.template_filter('fromjson')
    def fromjson_filter(value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return []
        return value or []

    @app.template_filter('tojson')
    def tojson_filter(value):
        return json.dumps(value)
