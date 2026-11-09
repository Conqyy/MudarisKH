"""Close topic references over the actual accepted original inventory."""


class InventoryReferenceError(ValueError):
    """An otherwise valid inventory refers to a missing or unrelated record."""


def validate_topic_links(value, earlier):
    # Imported here because extraction_inventory validates the record schema
    # before using this closure check.
    from src.supporting.extraction_inventory import identifier, requirement_id

    items, owners = set(), {}
    for response in [*earlier, value]:
        for row in response['items']:
            iid = identifier(row['origin'], row['itemType'])
            items.add(iid)
            for requirement in row['requirements']:
                owners.setdefault(requirement_id(requirement), set()).add(iid)
    for topic in value['topics']:
        linked = {identifier(row['origin'], row['itemType']) for row in topic['items']}
        if not linked <= items:
            raise InventoryReferenceError('Topic references an item absent from the extracted inventory')
        for requirement in topic['requirements']:
            actual = owners.get(requirement_id(requirement))
            if not actual:
                raise InventoryReferenceError(
                    'Topic requirement must copy the exact origin, text and category of an extracted requirement')
            if not actual <= linked:
                raise InventoryReferenceError('Topic requirement does not belong to its referenced item')
    return value
