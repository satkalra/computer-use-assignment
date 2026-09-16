import time


def slow_response(page, url_pattern: str, delay_ms: int) -> None:
    """Delay matching browser requests at the Playwright routing layer."""
    if delay_ms < 0:
        raise ValueError("delay_ms must not be negative")

    def delay_then_continue(route):
        time.sleep(delay_ms / 1000)
        route.continue_()

    page.route(url_pattern, delay_then_continue)


def strip_ids(page) -> None:
    """Remove document ids before application scripts execute."""
    page.add_init_script("""
        document.addEventListener('DOMContentLoaded', () => {
          for (const element of document.querySelectorAll('[id]')) {
            element.removeAttribute('id');
          }
        });
    """)
