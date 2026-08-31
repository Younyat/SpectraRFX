#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import sys
import threading

import sip
from PyQt5 import Qt, QtCore
from gnuradio import analog
from gnuradio import audio
from gnuradio import blocks
from gnuradio import filter
from gnuradio import gr
from gnuradio import qtgui
from gnuradio import uhd
from gnuradio.fft import window


def normalize_device_addr(device_addr: str) -> str:
    return str(device_addr).strip()


class WfmReceiver(gr.top_block, Qt.QWidget):
    def __init__(self, start_freq: float = 87e6, wav_path: str = "fm_audio.wav"):
        gr.top_block.__init__(self, "WFM Receiver", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("WFM Receiver")
        qtgui.util.check_set_qss()

        try:
            self.setWindowIcon(Qt.QIcon.fromTheme("gnuradio-grc"))
        except BaseException as exc:
            print(f"Qt GUI: Could not set Icon: {str(exc)}", file=sys.stderr)

        self.top_scroll_layout = Qt.QVBoxLayout()
        self.setLayout(self.top_scroll_layout)
        self.top_scroll = Qt.QScrollArea()
        self.top_scroll.setFrameStyle(Qt.QFrame.NoFrame)
        self.top_scroll_layout.addWidget(self.top_scroll)
        self.top_scroll.setWidgetResizable(True)
        self.top_widget = Qt.QWidget()
        self.top_scroll.setWidget(self.top_widget)
        self.top_layout = Qt.QVBoxLayout(self.top_widget)
        self.top_grid_layout = Qt.QGridLayout()
        self.top_layout.addLayout(self.top_grid_layout)

        self.settings = Qt.QSettings("gnuradio/flowgraphs", "spectrum_lab_wfm_receiver")
        try:
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except BaseException as exc:
            print(f"Qt GUI: Could not restore geometry: {str(exc)}", file=sys.stderr)

        self.flowgraph_started = threading.Event()
        self.samp_rate = 2 * 10**6
        self.freq = start_freq
        self.wav_path = wav_path

        self._freq_range = qtgui.Range(87 * 10**6, 107 * 10**6, 200 * 10**3, self.freq, 200)
        self._freq_win = qtgui.RangeWidget(
            self._freq_range,
            self.set_freq,
            "Frequency (Hz)",
            "counter_slider",
            float,
            QtCore.Qt.Horizontal,
        )
        self.top_layout.addWidget(self._freq_win)

        self.uhd_usrp_source_0 = uhd.usrp_source(
            normalize_device_addr(""),
            uhd.stream_args(cpu_format="fc32", args="", channels=[0]),
        )
        self.uhd_usrp_source_0.set_samp_rate(self.samp_rate)
        self.uhd_usrp_source_0.set_time_unknown_pps(uhd.time_spec(0))
        self.uhd_usrp_source_0.set_center_freq(self.freq, 0)
        self.uhd_usrp_source_0.set_antenna("RX2", 0)
        self.uhd_usrp_source_0.set_rx_agc(True, 0)

        self.rational_resampler_xxx_0 = filter.rational_resampler_ccc(
            interpolation=12,
            decimation=125,
            taps=[],
            fractional_bw=0,
        )
        self.analog_wfm_rcv_0 = analog.wfm_rcv(quad_rate=48000 * 4, audio_decimation=4)
        self.audio_sink_0 = audio.sink(48000, "", True)
        self.blocks_wavfile_sink_0 = blocks.wavfile_sink(
            self.wav_path,
            1,
            48000,
            blocks.FORMAT_WAV,
            blocks.FORMAT_PCM_16,
            False,
        )

        self.qtgui_time_sink_x_0 = qtgui.time_sink_c(1024, self.samp_rate, "", 1, None)
        self.qtgui_time_sink_x_0.set_update_time(0.10)
        self.qtgui_time_sink_x_0.set_y_axis(-1, 1)
        self.qtgui_time_sink_x_0.set_y_label("Amplitude", "")
        self.qtgui_time_sink_x_0.enable_tags(True)
        self.qtgui_time_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, qtgui.TRIG_SLOPE_POS, 0.0, 0, 0, "")
        self.qtgui_time_sink_x_0.enable_autoscale(True)
        self.qtgui_time_sink_x_0.enable_grid(False)
        self.qtgui_time_sink_x_0.enable_axis_labels(True)
        self.qtgui_time_sink_x_0.enable_control_panel(False)
        self.qtgui_time_sink_x_0.enable_stem_plot(False)

        labels = ["Signal 1", "Signal 2"]
        colors = ["blue", "red"]
        for i in range(2):
            self.qtgui_time_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_time_sink_x_0.set_line_width(i, 1)
            self.qtgui_time_sink_x_0.set_line_color(i, colors[i])
            self.qtgui_time_sink_x_0.set_line_style(i, 1)
            self.qtgui_time_sink_x_0.set_line_marker(i, -1)
            self.qtgui_time_sink_x_0.set_line_alpha(i, 1.0)

        self._qtgui_time_sink_x_0_win = sip.wrapinstance(self.qtgui_time_sink_x_0.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._qtgui_time_sink_x_0_win)

        self.qtgui_freq_sink_x_0 = qtgui.freq_sink_c(
            1024,
            window.WIN_BLACKMAN_hARRIS,
            self.freq,
            self.samp_rate,
            "",
            1,
            None,
        )
        self.qtgui_freq_sink_x_0.set_update_time(0.10)
        self.qtgui_freq_sink_x_0.set_y_axis(-140, 10)
        self.qtgui_freq_sink_x_0.set_y_label("Relative Gain", "dB")
        self.qtgui_freq_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, 0.0, 0, "")
        self.qtgui_freq_sink_x_0.enable_autoscale(False)
        self.qtgui_freq_sink_x_0.enable_grid(False)
        self.qtgui_freq_sink_x_0.set_fft_average(1.0)
        self.qtgui_freq_sink_x_0.enable_axis_labels(True)
        self.qtgui_freq_sink_x_0.enable_control_panel(False)
        self.qtgui_freq_sink_x_0.set_fft_window_normalized(False)
        self.qtgui_freq_sink_x_0.set_line_label(0, "Data 0")
        self.qtgui_freq_sink_x_0.set_line_width(0, 1)
        self.qtgui_freq_sink_x_0.set_line_color(0, "blue")
        self.qtgui_freq_sink_x_0.set_line_alpha(0, 1.0)

        self._qtgui_freq_sink_x_0_win = sip.wrapinstance(self.qtgui_freq_sink_x_0.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._qtgui_freq_sink_x_0_win)

        self.connect((self.uhd_usrp_source_0, 0), (self.qtgui_freq_sink_x_0, 0))
        self.connect((self.uhd_usrp_source_0, 0), (self.qtgui_time_sink_x_0, 0))
        self.connect((self.uhd_usrp_source_0, 0), (self.rational_resampler_xxx_0, 0))
        self.connect((self.rational_resampler_xxx_0, 0), (self.analog_wfm_rcv_0, 0))
        self.connect((self.analog_wfm_rcv_0, 0), (self.audio_sink_0, 0))
        self.connect((self.analog_wfm_rcv_0, 0), (self.blocks_wavfile_sink_0, 0))

    def closeEvent(self, event):
        self.settings = Qt.QSettings("gnuradio/flowgraphs", "spectrum_lab_wfm_receiver")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()
        event.accept()

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.qtgui_freq_sink_x_0.set_frequency_range(self.freq, self.samp_rate)
        self.qtgui_time_sink_x_0.set_samp_rate(self.samp_rate)
        self.uhd_usrp_source_0.set_samp_rate(self.samp_rate)

    def set_freq(self, freq):
        self.freq = freq
        self.qtgui_freq_sink_x_0.set_frequency_range(self.freq, self.samp_rate)
        self.uhd_usrp_source_0.set_center_freq(self.freq, 0)
        print(f"New frequency: {self.freq / 1e6:.1f} MHz")


def main():
    parser = argparse.ArgumentParser(description="WFM receiver with USRP, Qt GUI, and WAV recording")
    parser.add_argument("--freq", type=float, default=87.0, help="Start frequency in MHz")
    parser.add_argument("--output", type=str, default="fm_audio.wav", help="Output WAV file")
    args = parser.parse_args()

    qapp = Qt.QApplication(sys.argv[:1])
    tb = WfmReceiver(start_freq=args.freq * 1e6, wav_path=args.output)
    tb.start()
    tb.flowgraph_started.set()
    tb.show()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()
        Qt.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)
    qapp.exec_()


if __name__ == "__main__":
    main()
