from urllib.parse import parse_qs
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core.database import async_session_maker
from app.api.channels import service, events, constants
from . import models

router = APIRouter()


@router.websocket("/ws/channels/{token}")
async def channel_ws(ws: WebSocket, token: str):
    print("\n=== [WS][PUBLIC] New connection attempt ===")
    print("[WS][PUBLIC] token:", token)
    print("[WS][PUBLIC] client:", ws.client)

    await ws.accept()
    print("[WS][PUBLIC] accepted handshake")

    async with async_session_maker() as db:
        channel = await service.get_channel_by_token(db, token)

        print("[WS][PUBLIC] channel found:", bool(channel))

        if not channel:
            print("[WS][PUBLIC][ERROR] Invalid public token")
            await ws.close(code=1008)
            return

        from app.api.channels.connection_manager import manager

        await manager.connect(channel.id, ws)
        print("[WS][PUBLIC] connected to manager for channel", channel.id)

        role = constants.RECEIVER

        try:
            while True:
                data = await ws.receive_json()
                print("[WS][PUBLIC] received:", data)

                event = data.get("type")

                if event == "message":
                    msg = await events.handle_message(
                        db, channel, role, data["payload"]
                    )

                    out = {
                        "type": "message",
                        "data": {
                            "id": msg.id,
                            "sender_role": msg.sender_role,
                            "type": msg.type,
                            "payload": msg.payload,
                            "created_at": (
                                msg.created_at.isoformat() if msg.created_at else None
                            ),
                        },
                    }

                    print("[WS][PUBLIC] broadcasting message", out)

                    await manager.broadcast(channel.id, out)

                elif event == "form_submit":
                    msg = await events.handle_form_submit(
                        db, channel, data["payload"]["values"]
                    )

                    out = {
                        "type": "message",
                        "data": {
                            "id": msg.id,
                            "sender_role": msg.sender_role,
                            "type": msg.type,
                            "payload": msg.payload,
                            "created_at": (
                                msg.created_at.isoformat() if msg.created_at else None
                            ),
                        },
                    }

                    print("[WS][PUBLIC] broadcasting form_response", out)

                    await manager.broadcast(channel.id, out)

                elif event == "close":
                    print("[WS][PUBLIC] close event received")
                    await service.close_channel(db, channel)
                    await ws.close()

        except WebSocketDisconnect:
            print("[WS][PUBLIC] client disconnected")

        except Exception as e:
            print("[WS][PUBLIC][ERROR] runtime exception:", repr(e))

        finally:
            from app.api.channels.connection_manager import manager

            manager.disconnect(channel.id, ws)
            print("[WS][PUBLIC] disconnected from manager")


@router.websocket("/ws/channels/sender/{channel_id}")
async def channel_ws_sender(ws: WebSocket, channel_id: str):
    print("\n=== [WS][SENDER] New connection attempt ===")
    print("[WS][SENDER] channel_id:", channel_id)
    print("[WS][SENDER] client:", ws.client)

    await ws.accept()
    print("[WS][SENDER] accepted handshake")

    query_params = ws.query_params
    print("[WS][SENDER] raw query params:", query_params)

    token = query_params.get("token")
    if not token:
        print("[WS][SENDER] CLOSE: token missing")
        await ws.close(code=1008)
        return

    from app.core.auth import decode_token

    try:
        decoded = decode_token(token)
        print("[WS][SENDER] token decoded:", decoded)

        if not decoded.get("ok"):
            print("[WS][SENDER] CLOSE: token not ok")
            await ws.close(code=1008)
            return

        jwt_payload = decoded["payload"]
        print("[WS][SENDER] jwt payload:", jwt_payload)

        user_id = jwt_payload.get("uid")
        if not user_id:
            print("[WS][SENDER] CLOSE: uid missing in token")
            await ws.close(code=1008)
            return

        user_id = int(user_id)
        print("[WS][SENDER] authenticated user_id:", user_id)
        if not user_id:
            print("[WS][SENDER] CLOSE: uid missing in token")
            await ws.close(code=1008)
            return

        user_id = int(user_id)
        print("[WS][SENDER] authenticated user_id:", user_id)

    except Exception as e:
        print("[WS][SENDER] TOKEN DECODE FAILED:", repr(e))
        await ws.close(code=1008)
        return

    async with async_session_maker() as db:
        result = await db.execute(
            select(models.Channel)
            .where(models.Channel.id == channel_id)
            .where(models.Channel.sender_id == user_id)
        )
        channel = result.scalar_one_or_none()

        if not channel:
            print("[WS][SENDER] CLOSE: channel not found or not owned by user")
            await ws.close(code=1008)
            return

        print("[WS][SENDER] channel loaded OK:", channel.id)

        from app.api.channels.connection_manager import manager

        await manager.connect(channel.id, ws)
        print("[WS][SENDER] registered in connection manager")

        role = constants.SENDER

        try:
            while True:
                data = await ws.receive_json()
                print("[WS][SENDER] received:", data)

                event = data.get("type")

                if event == "message":
                    msg = await events.handle_message(
                        db, channel, role, data["payload"]
                    )

                    print("[WS][SENDER] message saved:", msg.id)

                    await manager.broadcast(
                        channel.id,
                        {
                            "type": "message",
                            "data": {
                                "id": msg.id,
                                "sender_role": msg.sender_role,
                                "type": msg.type,
                                "payload": msg.payload,
                                "created_at": (
                                    msg.created_at.isoformat()
                                    if msg.created_at
                                    else None
                                ),
                            },
                        },
                    )

                elif event == "close":
                    print("[WS][SENDER] close event received")
                    await service.close_channel(db, channel)
                    await ws.close()

        except WebSocketDisconnect:
            print("[WS][SENDER] normal disconnect")

        except Exception as e:
            print("[WS][SENDER] CRASHED WITH EXCEPTION:")
            print(type(e), repr(e))
            import traceback

            traceback.print_exc()
            try:
                await ws.close(code=1011)
            except:
                pass

        finally:
            manager.disconnect(channel.id, ws)
            print("[WS][SENDER] cleaned up connection")
