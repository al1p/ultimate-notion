"""Provides an object-based Notion API with all endpoints

This pydantic based API is often referred to as just `api` while the low-level
API of the [Notion Client SDK library](https://github.com/ramnes/notion-sdk-py)
is just referred to as `raw_api`.
"""

import logging
from typing import Dict, Union

from pydantic import parse_obj_as

from ultimate_notion.obj_api.blocks import Block, Database, Page
from ultimate_notion.obj_api.iterator import EndpointIterator, PropertyItemList
from ultimate_notion.obj_api.query import QueryBuilder
from ultimate_notion.obj_api.schema import PropertyObject
from ultimate_notion.obj_api.text import TextObject
from ultimate_notion.obj_api.types import DatabaseRef, ObjectReference, PageRef, ParentRef
from ultimate_notion.obj_api.props import PropertyItem, Title
from ultimate_notion.obj_api.user import User

logger = logging.getLogger(__name__)


class SessionError(Exception):
    """Raised when there are issues with the Notion session."""

    def __init__(self, message):
        """Initialize the `SessionError` with a supplied message.."""
        super().__init__(message)


class NotionAPI(object):
    """Object-based Notion API (pydantic) with all endpoints"""

    def __init__(self, client):
        self.client = client

        self.blocks = BlocksEndpoint(self)
        self.databases = DatabasesEndpoint(self)
        self.pages = PagesEndpoint(self)
        self.search = SearchEndpoint(self)
        self.users = UsersEndpoint(self)


class Endpoint(object):
    """Notional wrapper for the API endpoints."""

    def __init__(self, api: NotionAPI):
        """Initialize the `Endpoint` for the supplied session."""
        self.api = api


class BlocksEndpoint(Endpoint):
    """Notional interface to the API 'blocks' endpoint."""

    class ChildrenEndpoint(Endpoint):
        """Notional interface to the API 'blocks/children' endpoint."""

        @property
        def raw_api(self):
            """Return the underlying endpoint in the Notion SDK."""
            return self.api.client.blocks.children

        # https://developers.notion.com/reference/patch-block-children
        def append(self, parent, *blocks: Block):
            """Add the given blocks as children of the specified parent.

            The blocks info will be refreshed based on returned data.

            `parent` may be any suitable `ObjectReference` type.
            """

            parent_id = ObjectReference[parent].id

            children = [block.dict() for block in blocks if block is not None]

            logger.info("Appending %d blocks to %s ...", len(children), parent_id)

            data = self.raw_api.append(block_id=parent_id, children=children)

            if "results" in data:
                if len(blocks) == len(data["results"]):
                    for idx in range(len(blocks)):
                        block = blocks[idx]
                        result = data["results"][idx]
                        block.refresh(**result)

                else:
                    logger.warning("Unable to refresh results; size mismatch")

            else:
                logger.warning("Unable to refresh results; not provided")

            return parent

        # https://developers.notion.com/reference/get-block-children
        def list(self, parent):
            """Return all Blocks contained by the specified parent.

            `parent` may be any suitable `ObjectReference` type.
            """

            parent_id = ObjectReference[parent].id

            logger.info("Listing blocks for %s...", parent_id)

            blocks = EndpointIterator(endpoint=self.raw_api.list)

            return blocks(block_id=parent_id)

    def __init__(self, *args, **kwargs):
        """Initialize the `blocks` endpoint for the Notion API."""
        super().__init__(*args, **kwargs)

        self.children = BlocksEndpoint.ChildrenEndpoint(*args, **kwargs)

    @property
    def raw_api(self):
        """Return the underlying endpoint in the Notion SDK."""
        return self.api.client.blocks

    # https://developers.notion.com/reference/delete-a-block
    def delete(self, block):
        """Delete (archive) the specified Block.

        `block` may be any suitable `ObjectReference` type.
        """

        block_id = ObjectReference[block].id
        logger.info("Deleting block :: %s", block_id)

        data = self.raw_api.delete(block_id)

        return Block.parse_obj(data)

    def restore(self, block):
        """Restore (unarchive) the specified Block.

        `block` may be any suitable `ObjectReference` type.
        """

        block_id = ObjectReference[block].id
        logger.info("Restoring block :: %s", block_id)

        data = self.raw_api.update(block_id, archived=False)

        return Block.parse_obj(data)

    # https://developers.notion.com/reference/retrieve-a-block
    def retrieve(self, block):
        """Return the requested Block.

        `block` may be any suitable `ObjectReference` type.
        """

        block_id = ObjectReference[block].id
        logger.info("Retrieving block :: %s", block_id)

        data = self.raw_api.retrieve(block_id)

        return Block.parse_obj(data)

    # https://developers.notion.com/reference/update-a-block
    def update(self, block: Block):
        """Update the block content on the server.

        The block info will be refreshed to the latest version from the server.
        """

        logger.info("Updating block :: %s", block.id)

        data = self.raw_api.update(block.id.hex, **block.dict())

        return block.refresh(**data)


class DatabasesEndpoint(Endpoint):
    """Notional interface to the API 'databases' endpoint."""

    @property
    def raw_api(self):
        """Return the underlying endpoint in the Notion SDK."""
        return self.api.client.databases

    def _build_request(
        self,
        parent: ParentRef = None,
        schema: Dict[str, PropertyObject] = None,
        title=None,
    ):
        """Build a request payload from the given items.

        *NOTE* this method does not anticipate what the request will be used for and as
        such does not validate the inputs for any particular requests.
        """
        request = {}

        if parent is not None:
            request["parent"] = parent.dict()

        if title is not None:
            prop = TextObject[title]
            request["title"] = [prop.dict()]

        if schema is not None:
            request["properties"] = {
                name: value.dict() if value is not None else None for name, value in schema.items()
            }

        return request

    # https://developers.notion.com/reference/create-a-database
    def create(self, parent, schema: Dict[str, PropertyObject], title=None):
        """Add a database to the given Page parent.

        `parent` may be any suitable `PageRef` type.
        """

        parent_ref = PageRef[parent]

        logger.info("Creating database @ %s - %s", parent_ref.page_id, title)

        request = self._build_request(parent_ref, schema, title)

        data = self.raw_api.create(**request)

        return Database.parse_obj(data)

    # https://developers.notion.com/reference/retrieve-a-database
    def retrieve(self, dbref):
        """Return the Database with the given ID.

        `dbref` may be any suitable `DatabaseRef` type.
        """

        dbid = DatabaseRef[dbref].database_id

        logger.info("Retrieving database :: %s", dbid)

        data = self.raw_api.retrieve(dbid)

        return Database.parse_obj(data)

    # https://developers.notion.com/reference/update-a-database
    def update(self, dbref, title=None, schema: Dict[str, PropertyObject] = None):
        """Update the Database object on the server.

        The database info will be refreshed to the latest version from the server.

        `dbref` may be any suitable `DatabaseRef` type.
        """

        dbid = DatabaseRef[dbref].database_id

        logger.info("Updating database info :: %s", dbid)

        request = self._build_request(schema=schema, title=title)

        if request:
            data = self.raw_api.update(dbid, **request)
            dbref = dbref.refresh(**data)

        return dbref

    def delete(self, dbref):
        """Delete (archive) the specified Database.

        `dbref` may be any suitable `DatabaseRef` type.
        """

        dbid = DatabaseRef[dbref].database_id

        logger.info("Deleting database :: %s", dbid)

        return self.api.blocks.delete(dbid)

    def restore(self, dbref):
        """Restore (unarchive) the specified Database.

        `dbref` may be any suitable `DatabaseRef` type.
        """

        dbid = DatabaseRef[dbref].database_id

        logger.info("Restoring database :: %s", dbid)

        return self.api.blocks.restore(dbid)

    # https://developers.notion.com/reference/post-database-query
    def query(self, target):
        """Initialize a new Query object with the target data class.

        :param target: either a `DatabaseRef` type or an ORM class
        """
        cls = None
        dbid = DatabaseRef[target].database_id

        logger.info("Initializing database query :: {%s} [%s]", dbid, cls)

        return QueryBuilder(endpoint=self.raw_api.query, datatype=cls, database_id=dbid)


class PagesEndpoint(Endpoint):
    """Notional interface to the API 'pages' endpoint."""

    class PropertiesEndpoint(Endpoint):
        """Notional interface to the API 'pages/properties' endpoint."""

        @property
        def raw_api(self):
            """Return the underlying endpoint in the Notion SDK."""
            return self.api.client.pages.properties

        # https://developers.notion.com/reference/retrieve-a-page-property
        def retrieve(self, page_id, property_id):
            """Return the Property on a specific Page with the given ID."""

            logger.info("Retrieving property :: %s [%s]", property_id, page_id)

            data = self.raw_api.retrieve(page_id, property_id)

            # TODO should PropertyListItem return an iterator instead?
            return parse_obj_as(Union[PropertyItem, PropertyItemList], obj=data)

    def __init__(self, *args, **kwargs):
        """Initialize the `pages` endpoint for the Notion API."""
        super().__init__(*args, **kwargs)

        self.properties = PagesEndpoint.PropertiesEndpoint(*args, **kwargs)

    @property
    def raw_api(self):
        """Return the underlying endpoint in the Notion SDK."""
        return self.api.client.pages

    # https://developers.notion.com/reference/post-page
    def create(self, parent, title=None, properties=None, children=None):
        """Add a page to the given parent (Page or Database).

        `parent` may be a `ParentRef`, `Page`, or `Database` object.
        """

        if parent is None:
            raise ValueError("'parent' must be provided")

        if isinstance(parent, Page):
            parent = PageRef[parent]
        elif isinstance(parent, Database):
            parent = DatabaseRef[parent]
        elif not isinstance(parent, ParentRef):
            raise ValueError("Unsupported 'parent'")

        request = {"parent": parent.dict()}

        # the API requires a properties object, even if empty
        if properties is None:
            properties = {}

        if title is not None:
            properties["title"] = Title[title]

        request["properties"] = {name: prop.dict() if prop is not None else None for name, prop in properties.items()}

        if children is not None:
            request["children"] = [child.dict() for child in children if child is not None]

        logger.info("Creating page :: %s => %s", parent, title)

        data = self.raw_api.create(**request)

        return Page.parse_obj(data)

    def delete(self, page):
        """Delete (archive) the specified Page.

        `page` may be any suitable `PageRef` type.
        """

        return self.set(page, archived=True)

    def restore(self, page):
        """Restore (unarchive) the specified Page.

        `page` may be any suitable `PageRef` type.
        """

        return self.set(page, archived=False)

    # https://developers.notion.com/reference/retrieve-a-page
    def retrieve(self, page):
        """Return the requested Page.

        `page` may be any suitable `PageRef` type.
        """

        page_id = PageRef[page].page_id

        logger.info("Retrieving page :: %s", page_id)

        data = self.raw_api.retrieve(page_id)

        # XXX would it make sense to (optionally) expand the full properties here?
        # e.g. call the PropertiesEndpoint to make sure all data is retrieved

        return Page.parse_obj(data)

    # https://developers.notion.com/reference/patch-page
    def update(self, page: Page, **properties):
        """Update the Page object properties on the server.

        An optional `properties` may be specified as `"name"`: `PropertyValue` pairs.

        If `properties` are provided, only those values will be updated.
        If `properties` is empty, all page properties will be updated.

        The page info will be refreshed to the latest version from the server.
        """

        logger.info("Updating page info :: %s", page.id)

        if not properties:
            properties = page.properties

        props = {name: value.dict() if value is not None else None for name, value in properties.items()}

        data = self.raw_api.update(page.id.hex, properties=props)

        return page.refresh(**data)

    def set(self, page, cover=False, icon=False, archived=None):
        """Set specific page attributes (such as cover, icon, etc.) on the server.

        `page` may be any suitable `PageRef` type.

        To remove an attribute, set its value to None.
        """

        page_id = PageRef[page].page_id

        props = {}

        if cover is None:
            logger.info("Removing page cover :: %s", page_id)
            props["cover"] = {}
        elif cover is not False:
            logger.info("Setting page cover :: %s => %s", page_id, cover)
            props["cover"] = cover.dict()

        if icon is None:
            logger.info("Removing page icon :: %s", page_id)
            props["icon"] = {}
        elif icon is not False:
            logger.info("Setting page icon :: %s => %s", page_id, icon)
            props["icon"] = icon.dict()

        if archived is False:
            logger.info("Restoring page :: %s", page_id)
            props["archived"] = False
        elif archived is True:
            logger.info("Archiving page :: %s", page_id)
            props["archived"] = True

        data = self.raw_api.update(page_id.hex, **props)

        return page.refresh(**data)


class SearchEndpoint(Endpoint):
    """Notional interface to the API 'search' endpoint."""

    # https://developers.notion.com/reference/post-search
    def __call__(self, text=None):
        """Perform a search with the optional text.

        If specified, the call will perform a search with the given text.

        :return: a `QueryBuilder` with the requested search
        :rtype: query.QueryBuilder
        """

        params = {}

        if text is not None:
            params["query"] = text

        return QueryBuilder(endpoint=self.api.client.search, **params)


class UsersEndpoint(Endpoint):
    """Notional interface to the API 'users' endpoint."""

    @property
    def raw_api(self):
        """Return the underlying endpoint in the Notion SDK."""
        return self.api.client.users

    # https://developers.notion.com/reference/get-users
    def list(self):
        """Return an iterator for all users in the workspace."""

        logger.info("Listing known users...")

        users = EndpointIterator(endpoint=self.raw_api.list)

        return users()

    # https://developers.notion.com/reference/get-user
    def retrieve(self, user_id):
        """Return the User with the given ID."""

        logger.info("Retrieving user :: %s", user_id)

        data = self.raw_api.retrieve(user_id)

        return User.parse_obj(data)

    # https://developers.notion.com/reference/get-self
    def me(self):
        """Return the current bot User."""

        logger.info("Retrieving current integration bot")

        data = self.raw_api.me()

        return User.parse_obj(data)