"""Small request middleware used for speed and for Turbo (no full page reload) support."""
import threading

_state = threading.local()


def memo():
    """Per-request memo dict (only while a request is running; None otherwise, e.g. in scripts)."""
    return getattr(_state, "memo", None)


class PortalMiddleware:
    """1. Keeps a tiny per-request memo so the same lookup (holidays of a year) hits the database once.
    2. Turbo (the library that replaces full page reloads) only shows the page returned for a form
       submission when its status is 4xx. When a form has errors Django answers 200, so it is turned
       into 422 for Turbo requests. Normal browsers / the API are not affected.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _state.memo = {}
        try:
            response = self.get_response(request)
        finally:
            _state.memo = None
        if (
            request.method == "POST"
            and response.status_code == 200
            and "text/vnd.turbo-stream.html" in request.headers.get("Accept", "")
            and response.get("Content-Type", "").startswith("text/html")
        ):
            response.status_code = 422
        return response
