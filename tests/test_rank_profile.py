from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from commands import player_handlers
from graphics.rank_profile import draw_rank_profile


def test_rank_profile_renders_with_and_without_optional_fields():
    for current, peak in [({'tier': {'name': 'Platinum 2'}, 'rr': 0, 'last_change': -19},
                           {'tier': {'name': 'Diamond 1'}, 'rr': 55}), ({}, {})]:
        buffer = draw_rank_profile('Player#TAG', current, peak)
        with Image.open(buffer) as image:
            assert image.size == (1200, 500)


@pytest.mark.asyncio
async def test_rank_command_sends_image_with_rr_and_last_change(monkeypatch):
    interaction = SimpleNamespace(user=object(), response=SimpleNamespace(defer=AsyncMock()),
                                  followup=SimpleNamespace(send=AsyncMock()))
    current = {'tier': {'id': 16, 'name': 'Platinum 2'}, 'rr': 0, 'last_change': 22}
    peak = {'tier': {'id': 18, 'name': 'Diamond 1'}}
    api = AsyncMock(return_value={'current': current, 'peak': peak})
    icon_img = AsyncMock(return_value=None)
    renderer = Mock(return_value=BytesIO(b'png'))
    monkeypatch.setattr(player_handlers, 'draw_rank_profile', renderer)
    await player_handlers.rank_cmd(interaction, AFFINITY='eu', NO_PLAYER='missing', REGIONS={'eu'},
                                   cached_api=api, icon_maps=AsyncMock(return_value={'tiers': {'16': 'current', '18': 'peak'}}),
                                   icon_img=icon_img, load_accounts=Mock(),
                                   resolve_player=lambda *args: ('Friend', 'EU', 'eu'))
    assert renderer.call_args.args[:3] == ('Friend#EU', current, peak)
    assert icon_img.await_count == 2
    file = interaction.followup.send.await_args.kwargs['file']
    assert file.filename == 'rank.png'
    file.close()
