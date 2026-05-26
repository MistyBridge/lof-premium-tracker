DROP POLICY IF EXISTS "Users can upload own avatar" ON storage.objects;
DROP POLICY IF EXISTS "Users can update own avatar" ON storage.objects;
DROP POLICY IF EXISTS "Anyone can view avatars" ON storage.objects;

CREATE POLICY "Users can upload own avatar" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (bucket_id = 'avatars' AND name LIKE (auth.uid()::text || '.%'));

CREATE POLICY "Users can update own avatar" ON storage.objects
    FOR UPDATE TO authenticated
    USING (bucket_id = 'avatars' AND name LIKE (auth.uid()::text || '.%'));

CREATE POLICY "Anyone can view avatars" ON storage.objects
    FOR SELECT
    USING (bucket_id = 'avatars');
