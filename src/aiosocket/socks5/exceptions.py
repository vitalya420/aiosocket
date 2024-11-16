class Socks5Error(Exception):
    pass


class NoAcceptableMethods(Socks5Error):
    pass


class AuthenticationError(Socks5Error):
    pass


class ProxyAuthenticationError(Socks5Error):
    pass


class ProxyConnectionError(Socks5Error):
    pass


class ProxyError(Socks5Error):
    pass
