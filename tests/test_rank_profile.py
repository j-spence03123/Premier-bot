from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from commands import player_handlers
from graphics.rank_profile import at_peak, draw_rank_profile


def test_rank_profile_renders_with_and_without_optional_fields():
    for current, peak in [({'tier': {'name': 'Platinum 2'}, 'rr': 0, 'last_change': -19},
                           {'tier': {'name': 'Diamond 1'}, 'rr': 55}), ({}, {})]:
        buffer = draw_rank_profile('Player#TAG', current, peak)
        with Image.open(buffer) as image:
            assert image.size == (1200, 500)


def test_at_peak_detection():
    assert at_peak({'tier': {'id': 18, 'name': 'Diamond 1'}}, {'tier': {'id': 18, 'name': 'Diamond 1'}})
    assert not at_peak({'tier': {'id': 17}}, {'tier': {'id': 18}})
    assert not at_peak({'tier': {'id': 0, 'name': 'Unrated'}}, {'tier': {'id': 0, 'name': 'Unrated'}})
    assert at_peak({'tier': {'name': 'Gold 2'}}, {'tier': {'name': 'Gold 2'}})
    assert not at_peak({}, {})


def test_at_peak_card_renders_badge_and_borrows_current_rr():
    current = {'tier': {'id': 18, 'name': 'Diamond 1'}, 'rr': 42, 'last_change': 18}
    peak = {'tier': {'id': 18, 'name': 'Diamond 1'}, 'season': {'short': 'e9a3'}}
    with Image.open(draw_rank_profile('Player#TAG', current, peak)) as at, \
            Image.open(draw_rank_profile('Player#TAG', current, {**peak, 'tier': {'id': 19, 'name': 'Diamond 2'}})) as below:
        assert at.size == (1200, 500)
        assert at.getpixel((620, 300)) == (240, 99, 106)  # coral border on the peak panel
        assert below.getpixel((620, 300)) != (240, 99, 106)


def test_at_peak_card_never_shows_peak_rr_below_current(monkeypatch):
    from graphics import rank_profile
    labels = []
    original = rank_profile.ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        labels.append((xy[0], text))
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(rank_profile.ImageDraw.ImageDraw, "text", capture)
    current = {'tier': {'id': 18, 'name': 'Diamond 1'}, 'rr': 10}
    draw_rank_profile('Player#TAG', current, {'tier': {'id': 18, 'name': 'Diamond 1'}, 'rr': 0})
    assert (880, '10 RR') in labels and (880, '0 RR') not in labels
    labels.clear()
    draw_rank_profile('Player#TAG', current, {'tier': {'id': 19, 'name': 'Diamond 2'}, 'rr': 0})
    assert (880, '0 RR') in labels  # below peak, the peak's own RR is shown as reported


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
