-- Allow admin users to manage all profiles
CREATE POLICY "Admins can read all profiles" ON public.profiles
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin'));
CREATE POLICY "Admins can update all profiles" ON public.profiles
    FOR UPDATE USING (EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin'));
