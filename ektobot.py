#!/usr/bin/python

import os
import re
import json
import os.path
import zipfile
import argparse
import subprocess

def parse_name(filename):
    (dn, fn) = os.path.split(filename)
    m = re.match(r'^(.+) - (.+) - (\d+) - MP3\.zip$', fn)
    return {
        'artist': m.group(1),
        'album' : m.group(2),
        'year'  : m.group(3)
    }

def dir_name(album):
    return album['artist'].replace(' ', '_') + '_-_' + album['album'].replace(' ', '_') + '/'

def trackmeta(f):
    import eyeD3

    tag = eyeD3.tag.Mp3AudioFile(f).getTag()
    return {
        'num'   : tag.getTrackNum()[0],
        'artist': tag.getArtist(),
        'track' : tag.getTitle(),
        'bpm'   : tag.getBPM(),
        'year'  : tag.getYear(),
        'album' : tag.getAlbum()
    }

def run(args):
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    if p.returncode != 0:
        raise RuntimeError('Subprocess failed w/ return code {0}, stderr:\n {1}'.format(p.returncode, err))

def write_meta(dirname, meta, dry_run=False):
    if dry_run:
        return

    with open(os.path.join(dirname, 'ektobot.json'), 'w') as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)

def read_meta(dirname):
    with open(os.path.join(dirname, 'ektobot.json'), 'r') as fh:
        meta = json.load(fh)
    return meta

def unpack(archive, dry_run):
    #TODO write to temporary directory first (album artist fallback to dir name)
    #metadata: album artist + album name
    album = parse_name(archive)
    dirname = dir_name(album)
    if not dry_run:
        os.mkdir(dirname)

    with zipfile.ZipFile(archive, 'r') as zipf:
        print 'Extracting {0} to {1} ...'.format(archive, dirname)
        if not dry_run:
            zipf.extractall(dirname)
        names = zipf.namelist()

    write_meta(dirname, album, dry_run)

    return dirname

def videos(dirname, dry_run, outdir, cover):
    if not outdir:
        outdir = os.path.join(dirname, 'video')
    if not os.path.isdir(outdir):
        print 'Creating output directory {0}'.format(outdir)
        os.mkdir(outdir)

    if not cover:
        cover = os.path.join(dirname, 'folder.jpg')
    if not os.path.exists(cover):
        raise RuntimeError('Cover {0} not found'.format(cover))
    print 'Using image {0} as a cover'.format(cover)

    try:
        meta = read_meta(dirname)
        meta['tracks'] = []
    except IOError:
        # if there's no .json, read the album metadata from the first track
        meta = None

    (_, _, files) = next(os.walk(dirname))
    for infile in sorted(files):
        if not infile.endswith('.mp3'):
            continue

        tmeta = trackmeta(infile)
        if not meta:
            meta = {
                'artist': tmeta['artist'],
                'album' : tmeta['album'],
                'year'  : tmeta['year'],
                'tracks': []
            }
        # no need to write it to disk
        del tmeta['album']

        outfile = os.path.join(outdir, infile)
        outfile = outfile[:-3] + 'avi'
        meta['tracks'].append(tmeta)
        meta['tracks'][-1]['video_file'] = os.path.basename(outfile)
        infile = os.path.join(dirname, infile)

        print 'Converting {0} '.format(infile)
        print '        to {0} ...'.format(outfile)
        cmdline = ['ffmpeg',
                   '-loglevel', 'error', # be quiet
                   '-n',                 # do not overwrite output files
                   '-loop_input',        # video = image
                   '-i', cover,          # image
                   '-i', infile,         # audio
                   '-r', '1',            # 1fps
                   '-acodec', 'copy',    # do not recode audio
                   '-shortest',          # stop when the audio stops
                   outfile]
        try:
            if not dry_run:
                run(cmdline)
            else:
                print ' '.join(cmdline)
        except:
            print 'Converting {0} failed'.format(infile)
            raise

    write_meta(outdir, meta, False)
    print 'Done!'

ektoplazm_description = '''Artist: {artist}
Track: {track}
Album: {album}
Track number: {trackno}

Download the full album from Ektoplazm: {albumurl}'''

default_description = '''Artist: {artist}
Track: {track}
Album: {album}
Track number: {trackno}

Uploaded by ektobot http://github.com/mmilata/ektobot'''

templates = {
    'default'  : default_description,
    'ektoplazm': ektoplazm_description
}

def ytupload(dirname, dry_run, email, passwd, url=None):
    import getpass
    import gdata.youtube
    import gdata.youtube.service

    def yt_upload_video(yt_service, filename, title, description):
        media_group = gdata.media.Group(
            title       = gdata.media.Title(text=title),
            description = gdata.media.Description(description_type='plain', text=description),
            keywords    = gdata.media.Keywords(text='ektoplazm, music'),
            category    = gdata.media.Category(text='Music', label='Music', scheme='http://gdata.youtube.com/schemas/2007/categories.cat'),
            player      = None
        )

        video_entry = gdata.youtube.YouTubeVideoEntry(media=media_group)
        print 'Uploading video ...'
        new_entry = yt_service.InsertVideoEntry(video_entry, filename)
        return new_entry.id.text.split('/')[-1]

    def yt_create_playlist(yt_service, title, description, ids):
        playlist = yt_service.AddPlaylist(title, description)
        playlist_uri = playlist.feed_link[0].href #magic...
        for video_id in ids:
            playlist_entry = yt_service.AddPlaylistVideoEntryToPlaylist(playlist_uri, video_id)

    meta = read_meta(dirname)
    playlist_ids = []

    desc_template = templates['default']
    if url and 'ektoplazm.com' in url:
        desc_template = templates['ektoplazm']

    if not email:
        email = raw_input('youtube login: ') #XXX ektobot42@gmail.com

    if not passwd:
        passwd = getpass.getpass('password: ')

    yt_service = gdata.youtube.service.YouTubeService()
    #yt_service.ssl = True
    yt_service.developer_key = 'AI39si5d9grkxFwwm603wvh2toZxshBqVkCWalTT3UXB4b3W3TJz0bCwBv0qqRN9LeQDz0FAXOfCaSW35mAbtj3pnI8cXKu7YA'
    yt_service.source = 'ektobot'
    yt_service.client_id = 'ektobot-0'
    yt_service.email = email
    yt_service.password = passwd
    yt_service.ProgrammaticLogin()

    for trk in meta['tracks']:
        filename = os.path.join(dirname, trk['video_file'])
        title = '{0} - {1}'.format(trk['artist'], trk['track'])
        description = desc_template.format(
            artist = trk['artist'],
            track = trk['track'],
            album = meta['album'],
            trackno = trk['num'],
            albumurl = url if url else 'http://www.example.org/' #'http://www.ektoplazm.com/'
        )
        print 'Uploading {0} as {1} with description:\n{2}\n'.format(filename, title, description)
        if not dry_run:
            vid_id = yt_upload_video(yt_service, filename, title, description)
            playlist_ids.append(vid_id)

    if meta['artist'] == 'VA':
        pls_name = '{0} ({1})'.format(meta['album'], meta['year'])
    else:
        pls_name = '{0} - {1} ({2})'.format(meta['artist'], meta['album'], meta['year'])
    pls_description = ''
    print 'Creating playlist {0}'.format(pls_name)
    if not dry_run:
        yt_create_playlist(yt_service, pls_name, pls_description, playlist_ids)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='PROG')
    parser.add_argument('-n', '--dry-run', action='store_true', help='do not write/upload anything')
    subparsers = parser.add_subparsers(help='description', metavar='COMMAND', title='commands')

    parser_unpack = subparsers.add_parser('unpack', help='unpack .zip archive')
    parser_unpack.add_argument('archive', type=str, help='input file')
    parser_unpack.set_defaults(what='unpack')

    parser_videos = subparsers.add_parser('videos', help='convert audio files to yt-uploadable videos')
    parser_videos.add_argument('--image', type=str, help='album cover image (default folder.jpg)')
    parser_videos.add_argument('--outdir', type=str, help='video output directory (default video)')
    parser_videos.add_argument('dir', type=str, help='directory containing audio files') #TODO make it optional?
    parser_videos.set_defaults(what='videos')

    parser_yt = subparsers.add_parser('youtube', help='upload videos to youtube.com')
    parser_yt.add_argument('dir', type=str, help='directory containing subdirectory with videos')
    parser_yt.add_argument('-l', '--login', type=str, help='youtube login (email)')
    parser_yt.add_argument('-p', '--password', type=str, help='youtube password')
    parser_yt.add_argument('-u', '--url', type=str, help='ektoplazm url of the album')
    parser_yt.set_defaults(what='youtube')

    args = parser.parse_args()
    #print args
    if args.what == 'unpack':
        unpack(args.archive, args.dry_run)
    elif args.what == 'videos':
        videos(args.dir, args.dry_run, args.outdir, args.image)
    elif args.what == 'youtube':
        ytupload(args.dir, args.dry_run, args.login, args.password, args.url)
    else:
        assert False
