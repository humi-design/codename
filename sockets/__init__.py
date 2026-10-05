"""Socket.IO handler registration."""


def register_socket_handlers(socketio) -> None:
    # Importing the modules registers the @socketio.on handlers.
    from sockets import game_socket, session_socket  # noqa: F401

    return None
