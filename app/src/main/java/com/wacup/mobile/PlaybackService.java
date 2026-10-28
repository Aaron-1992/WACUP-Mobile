package com.wacup.mobile;

import androidx.annotation.Nullable;
import androidx.media3.session.MediaSession;
import androidx.media3.session.MediaSessionService;

/**
 * Keeps audio alive and gives the phone a real media notification, lock-screen
 * controls, Bluetooth controls and audio focus — the parts a Wine container can
 * never provide.
 */
public class PlaybackService extends MediaSessionService {

    private MediaSession session;

    @Override
    public void onCreate() {
        super.onCreate();
        MusicEngine engine = MusicEngine.get(this);
        session = new MediaSession.Builder(this, engine.player()).build();
    }

    @Nullable
    @Override
    public MediaSession onGetSession(MediaSession.ControllerInfo controllerInfo) {
        return session;
    }

    @Override
    public void onDestroy() {
        if (session != null) {
            session.release();
            session = null;
        }
        super.onDestroy();
    }
}
