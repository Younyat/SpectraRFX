# Pinned P0 reference dependencies

- GNU Radio `v3.10.12.0`, tag object
  `522b220f24cbf0df9789a2d8eff57ee3d3f58f52`, GPL-3.0.
- `bastibl/gr-ieee802-11`, branch `maint-3.10`, commit
  `ad0598e4a874f4b8e1f391a1e0323e80df2b34ff`, GPL-3.0.
- `bastibl/gr-foo`, branch `maint-3.10`, commit
  `4c2a471b0453b9dca669b2d9dfcbfba6278741d7`, GPL-3.0.

The upstream `gr-ieee802-11` project states that `maint-3.10` corresponds to
GNU Radio 3.10 and recommends validating `wifi_loopback.grc` before hardware.
This project invokes the reference stack as an isolated external process. It
does not copy or relabel its PHY implementation. Distribution of a bundled
worker must retain upstream license texts, copyright notices, source offer and
attribution, and must receive a separate GPL distribution review.
