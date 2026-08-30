"""Monday.com GraphQL query strings.

READ-ONLY BY CONSTRUCTION. There is no `mutation` keyword anywhere in this
package, and a test asserts that. Read-only enforcement is structural rather
than a runtime check that could be bypassed.
"""

LIST_BOARDS = """
query ListBoards($limit: Int!) {
  boards(limit: $limit, state: active) {
    id
    name
    items_count
  }
}
"""

BOARD_COLUMNS = """
query BoardColumns($boardId: [ID!]) {
  boards(ids: $boardId) {
    id
    name
    items_count
    columns {
      id
      title
      type
    }
  }
}
"""

# items_page with a cursor is the supported pagination mechanism on API
# versions 2023-10 and later. `text` gives the human-readable value; `value`
# gives the typed JSON. We keep BOTH -- the raw text is what makes the quality
# ledger auditable when a typed parse fails.
BOARD_ITEMS_FIRST_PAGE = """
query BoardItems($boardId: [ID!], $limit: Int!) {
  boards(ids: $boardId) {
    id
    name
    items_page(limit: $limit) {
      cursor
      items {
        id
        name
        column_values {
          id
          text
          value
          type
        }
      }
    }
  }
}
"""

BOARD_ITEMS_NEXT_PAGE = """
query BoardItemsNext($cursor: String!, $limit: Int!) {
  next_items_page(cursor: $cursor, limit: $limit) {
    cursor
    items {
      id
      name
      column_values {
        id
        text
        value
        type
      }
    }
  }
}
"""
