from app.api.channels import service, constants


async def handle_message(db, channel, role, payload):
    return await service.add_message(
        db,
        channel,
        role,
        payload["message_type"],
        payload["data"],
    )


async def handle_form_submit(db, channel, values):
    return await service.add_message(
        db,
        channel,
        constants.RECEIVER,
        constants.MESSAGE_FORM_RESPONSE,
        {"values": values},
    )
