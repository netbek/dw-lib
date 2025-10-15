class EmptyConfigException(Exception):
    pass


class PeerExistsException(Exception):
    pass


class PeerNotFoundException(Exception):
    pass


class MirrorExistsException(Exception):
    pass


class MirrorNotFoundException(Exception):
    pass


class DatabaseExistsException(Exception):
    pass


class DatabaseNotFoundException(Exception):
    pass


class SchemaExistsException(Exception):
    pass


class SchemaNotFoundException(Exception):
    pass


class TableExistsException(Exception):
    pass


class TableNotFoundException(Exception):
    pass


class UserExistsException(Exception):
    pass


class UserNotFoundException(Exception):
    pass


class PublicationExistsException(Exception):
    pass


class PublicationNotFoundException(Exception):
    pass
