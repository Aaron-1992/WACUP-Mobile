package com.wacup.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.media.audiofx.Equalizer;
import android.net.Uri;

import androidx.annotation.Nullable;
import androidx.media3.common.MediaItem;
import androidx.media3.common.PlaybackException;
import androidx.media3.common.Player;
import androidx.media3.exoplayer.ExoPlayer;

import com.wacup.mobile.playlist.Playlist;
import com.wacup.mobile.playlist.Track;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Process-wide player: one ExoPlayer, one playlist model, one equaliser.
 *
 * The media session service shares this instance so playback keeps going when the
 * activity is gone, and the skin windows read their state from it directly.
 */
public final class MusicEngine {

    public interface Listener {
        /** Something the windows draw has changed: track, state, position, volume. */
        void onPlayerStateChanged();
    }

    /** Ten bands, in the order the classic EQ shows them. */
    public static final String[] BAND_LABELS = {
            "60", "170", "310", "600", "1K", "3K", "6K", "12K", "14K", "16K"
    };
    public static final short BAND_MIN = -1200;   // millibels
    public static final short BAND_MAX = 1200;

    private static final String PREFS = "wacup_mobile";
    private static final String KEY_SKIN = "skin_path";
    private static final String KEY_FOLDER = "last_folder";
    private static final String KEY_VOLUME = "volume";
    private static final String KEY_SHUFFLE = "shuffle";
    private static final String KEY_REPEAT = "repeat";
    private static final String KEY_EQ_ON = "eq_on";
    private static final String KEY_EQ_PREFIX = "eq_band_";
    private static final String KEY_PLAYLIST = "last_playlist";

    private static MusicEngine instance;

    private final Context app;
    private final ExoPlayer player;
    private final Playlist playlist = new Playlist();
    private final List<Listener> listeners = new ArrayList<>();
    private final SharedPreferences prefs;

    private final float[] bandGains = new float[BAND_LABELS.length];
    private Equalizer equalizer;
    private int appliedAudioSession = -1;
    private boolean equalizerAttempted;
    private String lastError;
    private boolean eqEnabled;
    private int index = -1;

    public static synchronized MusicEngine get(Context context) {
        if (instance == null) {
            instance = new MusicEngine(context.getApplicationContext());
        }
        return instance;
    }

    private MusicEngine(Context app) {
        this.app = app;
        this.prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE);

        player = new ExoPlayer.Builder(app).build();
        player.setVolume(volumePercent() / 100f);
        player.setShuffleModeEnabled(prefs.getBoolean(KEY_SHUFFLE, false));
        player.setRepeatMode(prefs.getInt(KEY_REPEAT, Player.REPEAT_MODE_OFF));
        eqEnabled = prefs.getBoolean(KEY_EQ_ON, false);
        for (int i = 0; i < bandGains.length; i++) {
            bandGains[i] = prefs.getFloat(KEY_EQ_PREFIX + i, 0f);
        }

        player.addListener(new Player.Listener() {
            @Override
            public void onEvents(Player p, Player.Events events) {
                attachEqualizer(player.getAudioSessionId());
                notifyListeners();
            }

            @Override
            public void onMediaItemTransition(@Nullable MediaItem mediaItem, int reason) {
                index = player.getCurrentMediaItemIndex();
                notifyListeners();
            }

            @Override
            public void onPlayerError(PlaybackException error) {
                lastError = error.getErrorCodeName();
                // Skip a file the device cannot decode rather than stalling the queue.
                if (player.hasNextMediaItem()) {
                    player.seekToNextMediaItem();
                    player.prepare();
                    player.play();
                }
                notifyListeners();
            }
        });
    }

    public ExoPlayer player() {
        return player;
    }

    public Playlist playlist() {
        return playlist;
    }

    public void addListener(Listener listener) {
        if (!listeners.contains(listener)) listeners.add(listener);
    }

    public void removeListener(Listener listener) {
        listeners.remove(listener);
    }

    private void notifyListeners() {
        for (Listener l : new ArrayList<>(listeners)) {
            l.onPlayerStateChanged();
        }
    }

    // ------------------------------------------------------------------ queue

    public void setQueue(List<Track> tracks, int startIndex) {
        playlist.clear();
        playlist.addAll(tracks);

        List<MediaItem> items = new ArrayList<>(tracks.size());
        for (Track t : tracks) {
            items.add(new MediaItem.Builder()
                    .setUri(Uri.fromFile(t.file))
                    .setMediaMetadata(new androidx.media3.common.MediaMetadata.Builder()
                            .setTitle(t.title)
                            .build())
                    .build());
        }
        player.setMediaItems(items, Math.max(0, startIndex), 0L);
        player.prepare();
        index = Math.max(0, startIndex);
        notifyListeners();
    }

    public void playIndex(int newIndex) {
        if (newIndex < 0 || newIndex >= playlist.size()) return;
        if (player.getMediaItemCount() != playlist.size()) {
            setQueue(playlist.tracks, newIndex);
        } else {
            player.seekToDefaultPosition(newIndex);
        }
        ensureReady();
        player.play();
        index = newIndex;
        notifyListeners();
    }

    public int currentIndex() {
        int playerIndex = player.getCurrentMediaItemIndex();
        return playerIndex >= 0 ? playerIndex : index;
    }

    @Nullable
    public Track currentTrack() {
        return playlist.get(currentIndex());
    }

    public void togglePlayPause() {
        if (player.isPlaying()) {
            player.pause();
            notifyListeners();
            return;
        }
        // After stop() (or a playback error) ExoPlayer sits in STATE_IDLE and play()
        // is a no-op — it has to be prepared again first. This is what made the
        // player look permanently dead after pressing stop.
        if (player.getPlaybackState() == Player.STATE_IDLE) {
            if (player.getMediaItemCount() == 0 && playlist.size() > 0) {
                setQueue(playlist.tracks, 0);
                player.play();
            } else if (player.getMediaItemCount() > 0) {
                player.prepare();
                player.play();
            }
        } else {
            if (player.getMediaItemCount() == 0 && playlist.size() > 0) {
                setQueue(playlist.tracks, 0);
            }
            player.play();
        }
        notifyListeners();
    }

    /** ExoPlayer needs prepare() again after stop(), an error or a seek past the end. */
    private void ensureReady() {
        if (player.getPlaybackState() == Player.STATE_IDLE
                && player.getMediaItemCount() > 0) {
            player.prepare();
        }
    }

    public void stop() {
        player.stop();
        lastError = null;
        // Put the player back in a playable state so the play button works again.
        ensureReady();
        notifyListeners();
    }

    public void next() {
        ensureReady();
        if (player.hasNextMediaItem()) {
            player.seekToNextMediaItem();
            player.play();
        }
        notifyListeners();
    }

    public void previous() {
        ensureReady();
        if (player.hasPreviousMediaItem()) {
            player.seekToPreviousMediaItem();
            player.play();
        }
        notifyListeners();
    }

    public boolean isPlaying() {
        return player.isPlaying();
    }

    public long positionMs() {
        return player.getCurrentPosition();
    }

    public long durationMs() {
        long d = player.getDuration();
        if (d <= 0) {
            Track t = currentTrack();
            if (t != null && t.durationMs > 0) return t.durationMs;
            return 0;
        }
        return d;
    }

    /** Seeks using a 0..1 fraction of the bar (what the seek bar drags). */
    public void seekFraction(float fraction) {
        long duration = durationMs();
        if (duration <= 0) return;
        float clamped = Math.max(0f, Math.min(1f, fraction));
        player.seekTo((long) (duration * clamped));
        notifyListeners();
    }

    public float positionFraction() {
        long duration = durationMs();
        if (duration <= 0) return 0f;
        return Math.max(0f, Math.min(1f, positionMs() / (float) duration));
    }

    /** mm:ss, or the classic "--:--" when nothing is loaded. */
    public String timeLabel() {
        if (currentTrack() == null) return "--:--";
        long ms = positionMs();
        long totalSeconds = ms / 1000L;
        long m = totalSeconds / 60L;
        long s = totalSeconds % 60L;
        // Winamp shows a rolling minute counter rather than hours.
        if (m > 99) m = 99;
        return String.format(Locale.US, "%02d:%02d", m, s);
    }

    // ----------------------------------------------------------------- volume

    public int volumePercent() {
        return prefs.getInt(KEY_VOLUME, 100);
    }

    public void setVolumePercent(int percent) {
        int clamped = Math.max(0, Math.min(100, percent));
        player.setVolume(clamped / 100f);
        prefs.edit().putInt(KEY_VOLUME, clamped).apply();
        notifyListeners();
    }

    public boolean shuffle() {
        return player.getShuffleModeEnabled();
    }

    public void toggleShuffle() {
        boolean next = !player.getShuffleModeEnabled();
        player.setShuffleModeEnabled(next);
        prefs.edit().putBoolean(KEY_SHUFFLE, next).apply();
        notifyListeners();
    }

    public int repeatMode() {
        return player.getRepeatMode();
    }

    public void cycleRepeat() {
        int next;
        switch (player.getRepeatMode()) {
            case Player.REPEAT_MODE_OFF:
                next = Player.REPEAT_MODE_ALL;
                break;
            case Player.REPEAT_MODE_ALL:
                next = Player.REPEAT_MODE_ONE;
                break;
            default:
                next = Player.REPEAT_MODE_OFF;
                break;
        }
        player.setRepeatMode(next);
        prefs.edit().putInt(KEY_REPEAT, next).apply();
        notifyListeners();
    }

    public String repeatLabel() {
        switch (player.getRepeatMode()) {
            case Player.REPEAT_MODE_ALL: return "REP ALL";
            case Player.REPEAT_MODE_ONE: return "REP 1";
            default: return "REP OFF";
        }
    }

    // -------------------------------------------------------------------- eq

    public boolean eqEnabled() {
        return eqEnabled;
    }

    public void setEqEnabled(boolean on) {
        eqEnabled = on;
        prefs.edit().putBoolean(KEY_EQ_ON, on).apply();
        if (equalizer != null) {
            try {
                equalizer.setEnabled(on);
            } catch (Exception ignored) {
                // some devices refuse while the audio session is rebuilding
            }
        }
        notifyListeners();
    }

    public void toggleEq() {
        setEqEnabled(!eqEnabled);
    }

    public float[] bandGains() {
        return bandGains;
    }

    /** Applies a gain in the -12..+12 dB range (classic EQ range) to one band. */
    public void setBandGain(int band, float db) {
        if (band < 0 || band >= bandGains.length) return;
        float clamped = Math.max(-12f, Math.min(12f, db));
        bandGains[band] = clamped;
        prefs.edit().putFloat(KEY_EQ_PREFIX + band, clamped).apply();
        pushBandToEqualizer(band);
        notifyListeners();
    }

    private void pushBandToEqualizer(int bandIndex) {
        if (equalizer == null) return;
        try {
            short bands = equalizer.getNumberOfBands();
            if (bands <= 0) return;
            short mapped = (short) Math.min(bandIndex, bands - 1);
            short level = (short) (bandGains[bandIndex] * 100f);   // dB -> millibels
            level = (short) Math.max(equalizer.getBandLevelRange()[0],
                    Math.min(equalizer.getBandLevelRange()[1], level));
            equalizer.setBandLevel(mapped, level);
        } catch (Exception ignored) {
            // device EQ is best effort; the UI keeps working without it
        }
    }

    private void attachEqualizer(int audioSessionId) {
        // 0 means "no session yet"; attaching there grabs the global mix and on some
        // devices wedges audio output. Wait for the real session instead.
        if (audioSessionId == 0) return;
        if (audioSessionId == appliedAudioSession) return;
        appliedAudioSession = audioSessionId;
        releaseEqualizer();
        equalizerAttempted = true;
        try {
            equalizer = new Equalizer(0, audioSessionId);
            equalizer.setEnabled(eqEnabled);
            for (int i = 0; i < bandGains.length; i++) {
                pushBandToEqualizer(i);
            }
        } catch (Exception e) {
            equalizer = null;   // the UI keeps working, only the DSP is missing
        }
    }

    public boolean equalizerAvailable() {
        return equalizer != null;
    }

    @Nullable
    public String lastError() {
        return lastError;
    }

    public void clearError() {
        lastError = null;
    }

    private void releaseEqualizer() {
        if (equalizer != null) {
            try {
                equalizer.release();
            } catch (Exception ignored) {
                // ignore
            }
            equalizer = null;
        }
    }

    // --------------------------------------------------------------- storage

    public File lastFolder() {
        String path = prefs.getString(KEY_FOLDER, null);
        File dir = path == null ? null : new File(path);
        if (dir == null || !dir.isDirectory()) {
            dir = app.getExternalFilesDir(null);
        }
        if (dir == null) dir = app.getFilesDir();
        return dir;
    }

    public void setLastFolder(File dir) {
        if (dir != null && dir.isDirectory()) {
            prefs.edit().putString(KEY_FOLDER, dir.getAbsolutePath()).apply();
        }
    }

    @Nullable
    public File lastPlaylist() {
        String path = prefs.getString(KEY_PLAYLIST, null);
        return path == null ? null : new File(path);
    }

    public void setLastPlaylist(File file) {
        prefs.edit().putString(KEY_PLAYLIST, file == null ? null : file.getAbsolutePath()).apply();
    }

    @Nullable
    public File lastSkin() {
        String path = prefs.getString(KEY_SKIN, null);
        File f = path == null ? null : new File(path);
        return f != null && f.isFile() ? f : null;
    }

    public void setLastSkin(File file) {
        prefs.edit().putString(KEY_SKIN, file == null ? null : file.getAbsolutePath()).apply();
    }

    public void release() {
        releaseEqualizer();
        player.release();
    }
}
