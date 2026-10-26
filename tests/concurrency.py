import threading
from collections.abc import Callable

from app.core.errors import AppError

ATTEMPTS = 10


def run_concurrently[S, T](make: Callable[[], S], action: Callable[[S], T], attempts: int = ATTEMPTS) -> list[T | str]:
    """Cria um service por thread com `make`, libera todas juntas e roda `action`.

    Erros de domínio viram o `code` do erro; qualquer outro erro vira "unexpected ..." para a mensagem de falha.
    """
    barrier = threading.Barrier(attempts)
    results: list[T | str] = []
    lock = threading.Lock()

    def worker() -> None:
        service = make()
        barrier.wait()
        try:
            outcome: T | str = action(service)
        except AppError as exc:
            outcome = exc.code
        except Exception as exc:
            outcome = f"unexpected {type(exc).__name__}: {exc}"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results
